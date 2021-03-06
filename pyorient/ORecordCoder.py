from __future__ import print_function

#   Copyright 2012 Niko Usai <usai.niko@gmail.com>, http://mogui.it
#
#   this file is part of pyorient
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
# @BUG nested list e dict non funzionano nel parser

import re
import time

from OrientTypes import OrientRecordLink, OrientRecord, OrientBinaryObject
from datetime import date, datetime


# what we are going to collect
STATE_GUESS = 0
STATE_NAME = 1
STATE_VALUE = 2
STATE_STRING = 3
STATE_COMMA = 4
STATE_LINK = 5
STATE_NUMBER = 6
STATE_KEY = 7
STATE_BOOLEAN = 8
STATE_BUFFER = 9

# character classes
CCLASS_WORD = 1
CCLASS_NUMBER = 2
CCLASS_OTHER = 0

TTYPE_NAME = 0
TTYPE_CLASS = 1
TTYPE_NULL = 2
TTYPE_STRING = 3
TTYPE_COLLECTION_START = 4
TTYPE_COLLECTION_END = 5
TTYPE_LINK = 6
TTYPE_NUMBER = 7
TTYPE_MAP_START = 8
TTYPE_MAP_END = 9
TTYPE_BOOLEAN = 10
TTYPE_KEY = 11
TTYPE_EMBEDDED = 12
TTYPE_BUFFER = 13


class ORecordEncoder(object):
    """docstring for ORecordEncoder"""
    def __init__(self, oRecord):
        self._raw = self.__encode(oRecord)

    def __encode(self, record):

        raw = ''
        o_class = getattr(record, 'o_class', False)
        if o_class:
            raw = o_class + '@'

        fields = filter(
            lambda item: not item.startswith('_OrientRecord_'),
            record.__dict__)

        for idx, key in enumerate(fields):
            raw += key + ':'
            value = getattr(record, key)
            raw += self.parseValue(value)

            if idx < len(fields) - 1:
                # not last element
                raw += ','

        return raw

    def parseValue(self, value):
        if isinstance(value, unicode):
            ret = u'"' + value + u'"'
        elif isinstance(value, str):
            ret = '"' + value + '"'
        elif isinstance(value, int):
            ret = str(value)
        elif isinstance(value, float):
            ret = str(value) + 'f'
        elif isinstance(value, long):
            ret = str(value) + 'l'
        elif isinstance(value, datetime):
            ret = str(int(time.mktime(value.timetuple()))) + 't'
        elif isinstance(value, date):
            ret = str(int(time.mktime(value.timetuple())) * 1000) + 'a'
        elif isinstance(value, list):
            try:
                ret = '[' + ','.join(map(
                    lambda elem: self.parseValue(type(value[0])(elem)),
                    value)) + ']'
            except ValueError, e:
                raise Exception("wrong type commistion")
        elif isinstance(value, dict):
            ret = "{" + ','.join(map(
                lambda elem: '"' + elem + '":' + self.parseValue(value[elem]),
                value)) + '}'
        elif isinstance(value, OrientRecord):
            ret = "(" + self.__encode(value) + ")"
        elif isinstance(value, OrientRecordLink):
            ret = value.getHash()
        elif isinstance(value, OrientBinaryObject):
            ret = value.getRaw()
        else:
            ret = ''
        return ret

    def getRaw(self):
        return self._raw


class ORecordDecoder(object):
    """Porting of PHP OrientDBRecordDecoder"""

    def __init__(self, content):
        # public
        self.className = None
        self.content = content
        self.data = {}

        # private
        self._state = STATE_GUESS
        self._buffer = ''
        self._continue = True
        self._i = 0
        self._stackTokenValues = []
        self._stackTokenTypes = []
        self.isCollection = False
        self.isMap = False
        self.escape = False
        self._stateCase = [
            self.__state_guess, self.__state_name, self.__state_value,
            self.__state_string, self.__state_comma, self.__state_link,
            self.__state_number, self.__state_key, self.__state_boolean,
            self.__state_buffer]

        # start decoding
        self.__decode()

    def __decode(self):
        """docstring for decode"""

        while self._i < len(self.content) and self._continue:
            char = self.content[self._i:self._i+1]
            cClass = CCLASS_OTHER
            cCode = ord(char)
            if (cCode >= 65 and cCode <= 90) or (cCode >= 97 and cCode <= 122) or cCode == 95:
                cClass = CCLASS_WORD
            elif cCode >= 48 and cCode <= 57:
                cClass = CCLASS_NUMBER
            else:
                cClass = CCLASS_OTHER

            # pythonic switch case
            self._stateCase[self._state](char, cClass)
            tokenType = self.__stackGetLastType()

            if (
                    tokenType == TTYPE_NAME or tokenType == TTYPE_KEY or
                    tokenType == TTYPE_COLLECTION_START or tokenType == TTYPE_MAP_START):
                pass
            elif tokenType == TTYPE_CLASS:
                (ttype, tvalue) = self.__stackPop()
                self.className = tvalue
            elif (
                    tokenType == TTYPE_NUMBER or tokenType == TTYPE_STRING or
                    tokenType == TTYPE_BUFFER or tokenType == TTYPE_BOOLEAN or
                    tokenType == TTYPE_EMBEDDED or tokenType == TTYPE_LINK):
                if not self.isCollection and not self.isMap:
                    tt, tvalue = self.__stackPop()
                    tt, tname = self.__stackPop()
                    # print("%s -> %s" % (tname, tvalue))
                    self.data[tname] = tvalue
            elif tokenType == TTYPE_NULL:
                if not self.isCollection and not self.isMap:
                    self.__stackPop()
                    tt, tname = self.__stackPop()
                    self.data[tname] = None
            elif tokenType == TTYPE_COLLECTION_END:
                values = []
                while True:
                    searchToken, value = self.__stackPop()
                    if (
                            searchToken != TTYPE_COLLECTION_START and
                            searchToken != TTYPE_COLLECTION_END):
                        values.append(value)
                    if searchToken == TTYPE_COLLECTION_START:
                        break
                tt, tname = self.__stackPop()
                values.reverse()
                self.data[tname] = values
            elif tokenType == TTYPE_MAP_END:
                values = {}
                while True:
                    searchToken, value = self.__stackPop()
                    if searchToken == TTYPE_NULL:
                        value = None
                    if searchToken != TTYPE_MAP_START and searchToken != TTYPE_MAP_END:
                        tt, key = self.__stackPop()
                        values[key] = value
                    if searchToken == TTYPE_MAP_START:
                        break

                tt, tname = self.__stackPop()
                self.data[tname] = values
            else:
                # print("orly?")
                pass

    def __state_guess(self, char, cClass):
        """docstring for guess"""
        self._state = STATE_NAME
        self._buffer = char
        self._i += 1

    def __state_name(self, char, cClass):
        """docstring for name"""
        if char == ':':
            self._state = STATE_VALUE
            self.__stackPush(TTYPE_KEY)
        elif char == '@':
            self.__stackPush(TTYPE_CLASS)
        else:
            # trying to fastforward name collecting @TODO
            self._buffer += char

        self._i += 1

    def __state_value(self, char, cClass):
        """docstring for __stateValue"""
        if char == ',':
            # No value - switch state to comma
            self._state = STATE_COMMA
            # token type is null
            self.__stackPush(TTYPE_NULL)
        elif char == '"':
            # switch state to string collecting
            self._state = STATE_STRING
            self._i += 1
        elif char == '_':
            # switch state to string collecting
            self._state = STATE_BUFFER
            self._i += 1
        elif char == '#':
            # found hash - switch state to link
            self._state = STATE_LINK
            # add hash to value
            self._buffer = char
            self._i += 1
        elif char == '[':
            # [ found, state is still value
            self._state = STATE_VALUE
            # token type is collection start
            self.__stackPush(TTYPE_COLLECTION_START)
            # started collection
            self.isCollection = True
            self._i += 1
        elif char == ']':
            # ] found,
            self._state = STATE_COMMA
            # token type is collection end
            self.__stackPush(TTYPE_COLLECTION_END)
            # stopped collection
            self.isCollection = False
            self._i += 1
        elif char == '{':
            # found { switch state to name
            self._state = STATE_KEY
            # token type is map start
            self.__stackPush(TTYPE_MAP_START)
            # started map
            self.isMap = True
            self._i += 1
        elif char == '}':
            # } found
            # check if null value in the end of the map
            if self.__stackGetLastType() == TTYPE_KEY:
                # token type is map end
                self.__stackPush(TTYPE_NULL)
                return

            self._state = STATE_COMMA
            # token type is map end
            self.__stackPush(TTYPE_MAP_END)
            # stopped map
            self.isMap = False
            self._i += 1
        elif char == '(':
            # ( found, state is COMMA
            self._state = STATE_COMMA
            # increment position so we can transfer clean document
            self._i += 1
            parser = ORecordDecoder(self.content[self._i:])
            rec = OrientRecord(parser.data, o_class=parser.className)
            # @TODO missing rid and version from c api

            tokenValue = rec
            # token type is embedded
            self.__stackPush(TTYPE_EMBEDDED, tokenValue)
            # fast forward to embedded position
            self._i += parser._i
            # increment counter so we can continue on clean document
            self._i += 1

        elif char == ')':
            # end of current document reached
            self._continue = False

        elif char == 'f' or char == 't':
            # boolean found - switch state to boolean
            self._state = STATE_BOOLEAN
            self._buffer = char
            self._i += 1
        else:
            if cClass == CCLASS_NUMBER or char == '-':
                # number found - switch to number collecting
                self._state = STATE_NUMBER
                self._buffer = char
                self._i += 1
            elif char == False:
                self._i += 1
        # end __state_value()

    def __state_buffer(self, char, oClass):
        pos_end = self.content[self._i:].find('_')
        if pos_end > 1:
            self._buffer = self.content[self._i:(self._i + pos_end)]
            self._i += pos_end - 1

        if char == '_':
            self._state = STATE_COMMA
            self.__stackPush(TTYPE_BUFFER, OrientBinaryObject(self._buffer))
        self._i += 1

    def __state_string(self, char, cClass):
        if self._i < len(self.content):
            pos_quote = self.content[self._i:].find('"')
            pos_escape = self.content[self._i:].find('\\')

            if pos_escape != -1:
                pos = min(pos_quote, pos_escape)
            else:
                pos = pos_quote
        else:
            pos = False

        if pos and pos > 1:
            self._buffer += self.content[self._i:(self._i + pos)]
            self._i += pos
            return

        if char == '\\':
            if self.escape:
                self._buffer += char
                self.escape = False
            else:
                self.escape = True
        elif char == '"':
            if self.escape:
                self._buffer += char
                self.escape = False
            else:
                self._state = STATE_COMMA
                self.__stackPush(TTYPE_STRING)
        else:
            self._buffer += char

        self._i += 1

    def __state_comma(self, char, cClass):
        """docstring for __state_comma"""
        if char == ',':
            if self.isCollection:
                self._state = STATE_VALUE
            elif self.isMap:
                self._state = STATE_KEY
            else:
                self._state = STATE_GUESS
            self._i += 1
        else:
            self._state = STATE_VALUE

    def __state_link(self, char, cClass):
        """docstring for __state_link"""
        result = re.search('\d+:\d+', self.content[self._i:], re.I)
        if result and result.start() == 0:
            self._buffer = result.group()
            self._i += len(result.group())
        else:
            if char == ',':
                self._state = STATE_COMMA
            else:
                self._state = STATE_VALUE

            self.__stackPush(TTYPE_LINK, OrientRecordLink(self._buffer))
            # ORIENT TYPE LINK @TODO

    def __state_number(self, char, cClass):
        """docstring for __state_number"""
        result = re.search('[\d\.e-]+', self.content[self._i:], re.I)
        if result and result.start() == 0:
            self._buffer += result.group()
            self._i += len(result.group())
        else:
            # switch state to
            if char == ',':
                self._state = STATE_COMMA
            elif cClass == CCLASS_WORD:
                self._state = STATE_COMMA
                self._i += 1
            else:
                self._state = STATE_VALUE
            # fill token
            if char == 'b' or char == 's':
                tokenValue = int(self._buffer)
            elif char == 'l':
                tokenValue = long(self._buffer)
            elif char == 'f' or char == 'd':
                tokenValue = float(self._buffer)
            elif char == 't':
                tokenValue = datetime.fromtimestamp(float(self._buffer))
            elif char == 'a':
                tokenValue = date.fromtimestamp(float(self._buffer)/1000)
            else:
                tokenValue = int(self._buffer)

            # token type is a number
            self.__stackPush(TTYPE_NUMBER, tokenValue)

    def __state_key(self, char, cClass):
        """docstring for __state_key"""
        if char == ":":
            self._state = STATE_VALUE
            self.__stackPush(TTYPE_KEY)
        else:
            # Fast-forwarding to " symbol
            if self._i < len(self.content):
                pos = self.content.find('"', self._i+1)
            else:
                pos = False

            if pos != False and pos > self._i:
                # Before " symbol
                self._buffer = self.content[self._i+1:pos]
                self._i = pos
        self._i += 1

    def __state_boolean(self, char, cClass):
        """docstring for __state_boolean"""
        tokenValue = False
        if self.content[self._i:].find('rue') == self._i:
            tokenValue = True
            self._i += 3
        elif self.content[self._i:].find('alse') == self._i:
            tokenValue = False
            self._i += 4
        else:
            # @TODO raise an exception
            pass
        self._state = STATE_COMMA
        self.__stackPush(TTYPE_BOOLEAN, tokenValue)

    def __stackPush(self, tokenType, tokenValue=None):
        """docstring for __stackPush"""
        self._stackTokenTypes.append(tokenType)
        if tokenValue == None:
            tokenValue = self._buffer

        self._stackTokenValues.append(tokenValue)
        self._buffer = ''

    def __stackPop(self):
        """ pop value from stack """
        return (self._stackTokenTypes.pop(), self._stackTokenValues.pop())

    def __stackGetLastType(self):
        """docstring for __stackGetLastType"""
        if len(self._stackTokenTypes) > 0:
            return self._stackTokenTypes[-1]
        else:
            return None

    def __stackGetLastKey(self):
        """ returns las tinserted value"""
        depth = False

        for i in range(len(self._stackTokenTypes)-1, -1, -1):
            if self._stackTokenTypes[i] == TTYPE_NAME:
                depth = i
                break

        if depth != False:
            return self._stackTokenValues[depth]
