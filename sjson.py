#!/usr/bin/python
#
#  sjson.py
#
#  Created by Mike Weaver on 2016-10-27.
#

import sys
import re

#
# Tokens
#

class Token:

	def __init__(self, text, line, pos):
		self.text = text
		self.lineNumber = line
		self.charPosition = pos

	def __str__(self):
		return '{{{0}:`{1}`,{2}:{3}}}'.format(self.__class__.__name__[:-5].upper(), self.text, self.lineNumber, self.charPosition)

	def pushChar(self, chr):
		self.text += chr

	def popChar(self):
		self.text = self.text[:-1]

class IndentToken(Token):
	pass

class NameToken(Token):
	pass

class CommaToken(Token):
	pass

class ColonToken(Token):
	pass

class DoubleColonToken(Token):
	pass

class CommentToken(Token):
	pass

#
# Lexer
#

class Lexer:

	def __init__(self, file):
		self.file = file
		self.lineNumber = 0
		self.charPosition = 0

	#
	# Managing tokens
	#

	def currentToken(self):
		return self.tokenList[-1] if self.tokenList else None

	def twoConsecutiveColons(self, token):
		latest = self.currentToken()
		return (latest and isinstance(latest, ColonToken) and ':' == latest.text and isinstance(token, ColonToken))

	def addToken(self, token):
		if self.twoConsecutiveColons(token):
			original = self.tokenList.pop()
			token = DoubleColonToken('::', original.lineNumber, original.charPosition)
		self.tokenList.append(token)

	#
	# Scanning characters and scanner callbacks
	#

	def scan_POUND(self, chr):
		token = self.currentToken()
		if token and isinstance(token, NameToken) and token.text.endswith('#'):
			token.popChar()
			if not token.text:
				self.tokenList.pop()
			dptoken = CommentToken('##', self.lineNumber, self.charPosition-1)
			self.addToken(dptoken)
		else:
			self.scan_CHARACTER('#')

	def scan_CHARACTER(self, chr):
		token = self.currentToken()
		if not token or not isinstance(token, NameToken):
			self.addToken(NameToken(chr, self.lineNumber, self.charPosition))
		elif isinstance(token, NameToken):
			token.pushChar(chr)

	def scanLine(self, line):
		self.tokenList = []
		self.charPosition = 0
		stringMode = False
		commentMode = False
		prev = ''
		for chr in line:
			# EOL character
			if '\n' == chr:
				pass
			# Comment mode
			elif commentMode:
				token = self.currentToken()
				assert token and isinstance(token, CommentToken)
				token.pushChar(chr)
			# Whitespace
			elif '\t' == chr or ' ' == chr:
				token = self.currentToken()
				if not token:
					self.addToken(IndentToken(chr, self.lineNumber, self.charPosition))
				else:
					token.pushChar(chr)
			# Colon
			elif ':' == chr and not stringMode:
				self.addToken(ColonToken(chr, self.lineNumber, self.charPosition))
			# Comma
			elif ',' == chr and not stringMode:
				self.addToken(CommaToken(chr, self.lineNumber, self.charPosition))
			# Pound
			elif '#' == chr and not stringMode:
				self.scan_POUND(chr)
				if '#' == prev:
					commentMode = True
			# Beginning quote
			elif '"' == chr and not stringMode:
				self.scan_CHARACTER(chr)
				stringMode =True
			# Ending quote
			elif '"' == chr and stringMode:
				if '\\' != prev:
					stringMode = False
				self.scan_CHARACTER(chr)
			# Any character
			else:
				self.scan_CHARACTER(chr)
			prev = chr
			self.charPosition += 1
		return self.tokenList

	def getTokens(self):
		for line in self.file:
			yield self.scanLine(line)
			self.lineNumber += 1

#
# Node classes
#

class Node:

	indent = ''

	def __init__(self, indent, payload = None, children = None, keys = None):
		self.indent = indent #NOTE: This will be an IndentToken or None (for the outermost array).
		self.childGroups = [ children ] if children else [ [] ] #NOTE: These will be an array of arrays of Nodes.
		self.payload = payload #NOTE: This will be a Token or None.
		self.keys = keys #This will be an array of Strings

	def __str__(self):
		result = Node.indent + self.__class__.__name__[:-4].upper() + ':'
		if self.payload:
			result += ' payload=`' + self.payload.text.strip() + '`'
		if self.keys:
			result += ' keys=[' + ', '.join(c.payload.text.strip() for c in self.keys.childGroups[-1]) + ']'
		if self.childGroups[-1]:
			result += ' children=['
			i = 1
			Node.indent += ' '*5
			for children in self.childGroups:
				result += '\n' + Node.indent + 'Group ' + str(i) + ': [\n'
				Node.indent += ' '*5
				result += '\n'.join(str(c) for c in children)
				Node.indent = Node.indent[:-5]
				result += '\n' + Node.indent + ']'
				i += 1
			Node.indent = Node.indent[:-5]
			result += '\n' + Node.indent + ']'
		return result

	def addChild(self, child, flag):
		if self.childGroups[-1] and flag:
			self.childGroups.append([])
		group = self.childGroups[-1]
		group.append(child)

	def writeOpen(self, char, stream, pretty):
		stream.write(char)
		Node.indent += ' '*5
		if pretty: stream.write('\n' + Node.indent)

	def writeClose(self, char, stream, pretty):
		Node.indent = Node.indent[:-5]
		if pretty: stream.write('\n' + Node.indent)
		stream.write(char)

	def writeSep(self, char, stream, pretty):
		stream.write(char)
		if pretty: stream.write('\n' + Node.indent)

	def writeChildren(self, stream, pretty):
		needsOuterWrap = (self.childGroups and 1<len(self.childGroups))
		if needsOuterWrap: self.writeOpen('[', stream, pretty)
		doneOneGroup = False
		for children in self.childGroups:
			braces = (children and all(isinstance(c, PairNode) for c in children))
			if doneOneGroup: self.writeSep(',', stream, pretty)
			needsWrap = (children and (1<len(children) or braces))
			if needsWrap: self.writeOpen('{' if braces else '[', stream, pretty)
			doneOneChild = False
			for c in children:
				if doneOneChild: self.writeSep(',', stream, pretty)
				needsBraces = (not braces and isinstance(c, PairNode))
				needsIndent = (len(c.childGroups) > 1 or len(c.childGroups[0]) > 1)
				if needsBraces: self.writeOpen('{', stream, pretty and needsIndent)
				c.output(stream, pretty)
				if needsBraces: self.writeClose('}', stream, pretty and needsIndent)
				doneOneChild = True
			if needsWrap: self.writeClose('}' if braces else ']', stream, pretty)
			doneOneGroup = True
		if needsOuterWrap: self.writeClose(']', stream, pretty)

	def writePayload(self, stream, literals=True):
		stripped = self.payload.text.strip()
		if literals and (stripped == 'null' or stripped == 'false' or stripped == 'true'):
			stream.write(stripped)
		elif literals and re.match('^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$', stripped):
			stream.write(stripped)
		elif stripped.endswith('"') and stripped.startswith('"'):
			stream.write(stripped)
		else:
			stream.write('"' + stripped + '"')


class StringNode(Node):

	def output(self, stream, pretty):
		self.writePayload(stream)

class PairNode(Node):

	def output(self, stream, pretty):
		if self.payload:
			self.writePayload(stream, False)
		if self.payload or self.childGroups[0]:
			stream.write(':')
			if pretty: stream.write(' ')
		self.writeChildren(stream, pretty)

class ArrayNode(Node):

	def output(self, stream, pretty):
		needsBrackets = ((self.payload and '-' == self.payload.text) or not self.childGroups[0] or (1 == len(self.childGroups) and 1 == len(self.childGroups[0]) and not isinstance(self.childGroups[0][0], PairNode) and not isinstance(self.childGroups[0][0], ArrayNode)))
		if needsBrackets: self.writeOpen('[', stream, pretty and self.childGroups[0])
		self.writeChildren(stream, pretty)
		if needsBrackets: self.writeClose(']', stream, pretty and self.childGroups[0])

class RecordNode(ArrayNode):

	def zip(self, keys, list):
		i = 0
		result = []
		while i < len(keys):
			if i < len(list) and list[i].payload.text:
				result.append(PairNode(self.indent, keys[i].payload, [ list[i] ]))
			i += 1
		return result

	def addChild(self, child, flag):
		assert(isinstance(child, ArrayNode))
		convert = self.zip(self.keys.childGroups[0], child.childGroups[0])
		Node.addChild(self, ArrayNode(child.indent, None, convert), flag)

#
# Parser
#

class Parser:

	def __init__(self, lexer):
		self.lexer = lexer
		self.skipEmpty = True #NOTE: Controls when parsing value lists if consecutive commas generate a Node

	def parseArrayMarker(self, tokens):
		target = 1 if isinstance(tokens[0], IndentToken) else 0
		if 1+target == len(tokens) and isinstance(tokens[target], NameToken) and '-' == tokens[target].text.strip():
			self.parsedNode = ArrayNode(self.indent, tokens[target])
			return True
		return False

	def parseOpenPair(self, tokens):
		target = 1 if isinstance(tokens[0], IndentToken) else 0
		if 2+target == len(tokens) and isinstance(tokens[target], NameToken) and isinstance(tokens[target+1], ColonToken):
			self.parsedNode = PairNode(self.indent, tokens[target])
			return True
		return False

	def parseRecordDef(self, tokens):
		target = 1 if isinstance(tokens[0], IndentToken) else 0
		name = None
		if 1+target < len(tokens) and isinstance(tokens[target], NameToken):
			name = tokens[target]
			target += 1
		if not (1+target < len(tokens)) or not isinstance(tokens[target], DoubleColonToken):
			return False
		if not self.parseValueList(tokens[target+1:], True): #NOTE: We turn stringOnly mode on for this call to parseValueList().
			return False
		keys = self.parsedNode
		#TODO: check for errors, if the parsedNode is not at array, turn it into one. If it is empty, we have an error
		self.parsedNode = RecordNode(self.indent, name, None, keys)
		return True

	def parseString(self, tokens):
		assert tokens
		target = 1 if isinstance(tokens[0], IndentToken) else 0
		self.parsedNode = StringNode(self.indent, self.mergeTokens(tokens[target:]))
		return True

	def parseValue(self, tokens):
		'''Parses a single value, the stuff you would find between commas.'''
		assert tokens
		target = 1 if isinstance(tokens[0], IndentToken) else 0
		if 1+target == len(tokens) and isinstance(tokens[target], CommaToken):
			self.parsedNode = ArrayNode(self.indent)
			return True
		if 1+target == len(tokens) and isinstance(tokens[target], ColonToken):
			self.parsedNode = PairNode(self.indent)
			return True
		if 2+target < len(tokens) and isinstance(tokens[target], NameToken) and isinstance(tokens[target+1], ColonToken):
			self.parsedNode = PairNode(self.indent, tokens[target], [ StringNode(self.indent, self.mergeTokens(tokens[target+2:])) ])
			return True
		#TODO: let's test for explicit {COLON}{NAME} or {NAME}{COLON} and create a partial pair that will fail when it gets to JSON
		if any(isinstance(t, ColonToken) for t in tokens):
			# here we put out a warning that the user has a partial pair that will be treated as a string
			pass
		self.parsedNode = StringNode(self.indent, self.mergeTokens(tokens[target:]))
		return True

	def parseValueList(self, tokens, stringOnly = False):
		'''Parses a comma-separated list of tokens.'''
		ndlist = []
		commaFlag = False
		target = 1 if isinstance(tokens[0], IndentToken) else 0
		while target < len(tokens):
			tklist = []
			while target < len(tokens) and isinstance(tokens[target], CommaToken):
				commaFlag = True
				if not self.skipEmpty and target > 0 and isinstance(tokens[target-1], CommaToken):
					ndlist.append(StringNode(self.indent, NameToken('', tokens[target].lineNumber, tokens[target].charPosition)))
				target += 1
			while target < len(tokens) and not isinstance(tokens[target], CommaToken):
				tklist.append(tokens[target])
				target += 1
			if tklist and ((stringOnly and self.parseString(tklist)) or self.parseValue(tklist)):
				ndlist.append(self.parsedNode)
		if 1 == len(ndlist) and not commaFlag and not stringOnly and self.skipEmpty:
			self.parsedNode = ndlist[0]
		else:
			self.parsedNode = ArrayNode(self.indent, None, ndlist)
		return True

	def mergeTokens(self, tokens):
		'''Combines the text members from each token in the list into a single Name token.'''
		assert tokens
		newText = reduce(lambda a, b: a + b, map(lambda a: a.text, tokens), '')
		return NameToken(newText, tokens[0].lineNumber, tokens[0].charPosition)

	def getNodes(self):
		'''Steps through all the tokens returned from the lexer and constructs a hierarchy of Node objects.'''
		blankLineFlag = False
		indent_none = IndentToken('', 0, 0)
		nodeStack = [ ArrayNode(None) ]
		lineNumber = 0
		for tokenList in self.lexer.getTokens():
#			print 'line ' + str(lineNumber) + ': ' + ', '.join(str(t) for t in tokenList) + '\n'
			# Pay attention to blank lines.
			if all(isinstance(t, IndentToken) for t in tokenList):
				blankLineFlag = True
				lineNumber += 1
				continue
			# Filter the tokens to remove comment-only lines, etc.
			if all(isinstance(t, IndentToken) or isinstance(t, CommentToken) for t in tokenList):
				lineNumber += 1
				continue
			tokenList = filter(lambda t: not isinstance(t, CommentToken), tokenList)
			self.indent = tokenList[0] if isinstance(tokenList[0], IndentToken) else indent_none
			# Find the right place for new nodes, popping nodes off the stack if needed.
			while nodeStack:
				cursor = nodeStack[-1]
				if not cursor.indent or (self.indent.text > cursor.indent.text and self.indent.text.startswith(cursor.indent.text)):
					if cursor.childGroups[-1] and cursor.childGroups[-1][-1].indent.text != self.indent.text:
						# we have an error, because the indent is greater than the parent, but doesn't match prior siblings
						print "error because indent is greater than parent, but doesn't match prior siblings"
						return None
					break
				else:
					finished = nodeStack.pop()
					#TODO: this might be a place to examine the just-popped container and emit warnings if stuff is empty that we expected to have children.
					#NOTE: if we run off the end of the file, we'll never see these pops
			if not nodeStack:
				print 'error: we popped our way off the node stack'
				return None
			# Generate the new node from the current line of tokens
			cursor = nodeStack[-1]
			if cursor.keys:
				self.skipEmpty = False
				if self.parseValueList(tokenList):
					newNode = self.parsedNode
				else:
					print 'error parsing field list in table mode'
					return None
				self.skipEmpty = True
			elif self.parseArrayMarker(tokenList) or self.parseOpenPair(tokenList) or self.parseRecordDef(tokenList):
				newNode = self.parsedNode
				nodeStack.append(newNode)
			elif self.parseValueList(tokenList):
				newNode = self.parsedNode
			else:
				print 'error: unable to parse anything on this line: ' + lineNumber
				return None
			cursor.addChild(newNode, blankLineFlag)
			blankLineFlag = False
			lineNumber += 1
		return nodeStack[0]

#
# Interactive mode
#

if __name__ == '__main__':
	lexer = Lexer(sys.stdin)
	parser = Parser(lexer)
	nodeTree = parser.getNodes()
# 	sys.stdout.write(str(nodeTree))
# 	sys.stdout.write('\n')
	nodeTree.output(sys.stdout, True)
	print
