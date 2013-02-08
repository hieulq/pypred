"""
This module provides the AST nodes that are used to
represent and later, evaluate a predicate.
"""
import re
from functools import wraps


def failure_info(func):
    "Helper to provide error information on failure"
    @wraps(func)
    def wrapper(self, pred, doc, info=None):
        r = func(self, pred, doc, info)
        if not r and info is not None:
            self.failure_info(pred, doc, info)
        return r
    return wrapper


class Node(object):
    "Root object in the AST tree"
    def __init__(self):
        # Set to true in our _validate method
        self.position = "line: ?, col: ?"

    def set_position(self, line, col):
        self.position = "line: %d, col %d" % (line, col)

    def name(self):
        "Provides human name with location"
        cls = self.__class__.__name__
        return "%s at %s" % (cls, self.position)

    def description(self, buf=None, depth=0):
        """
        Provides a human readable tree description
        """
        if not buf:
            buf = ""
        pad = depth * "\t"
        buf += pad + self.name() + "\n"
        if hasattr(self, "left"):
            buf = self.left.description(buf, depth+1)
        if hasattr(self, "right"):
            buf = self.right.description(buf, depth+1)
        return buf

    def __repr__(self):
        """
        Provides a representation that is useful to check the AST
        but is not necesarily very usable as a user error message.
        """
        name = self.__class__.__name__
        r = name
        if hasattr(self, "type"):
            r += " t:" + str(self.type)
        if hasattr(self, "value"):
            r += " v:" + str(self.value)
        if hasattr(self, "left"):
            r += " l:" + self.left.__class__.__name__
        if hasattr(self, "right"):
            r += " r:" + self.right.__class__.__name__
        return r

    def pre(self, func):
        """
        Performs a pre-order traversal of the
        tree, and invokes a callback for each node.
        """
        func(self)
        if hasattr(self, "left"):
            self.left.pre(func)
        if hasattr(self, "right"):
            self.right.pre(func)

    def validate(self, info=None):
        """
        Performs semantic validation of the Node.
        Attaches information to an info object,
        which is returned
        """
        if info is None:
            info = {"errors": [], "regex": {}}

        # Post order validation
        v = True
        if hasattr(self, "left"):
            sub_v, _ =  self.left.validate(info)
            v &= sub_v
        if hasattr(self, "right"):
            sub_v, _ = self.right.validate(info)
            v &= sub_v

        v &= self._validate(info)
        return (v, info)

    def _validate(self, info):
        "Validates the node"
        return True

    def evaluate(self, pred, document):
        """
        Evaluates the AST tree against the document for the
        given predicate. Returns either True or False
        """
        return bool(self.eval(pred, document, None))

    def analyze(self, pred, document):
        """
        Evaluates the AST tree against the document for the
        given predicate and provides a dictionary with detailed
        information about the evaluate and failure reasons
        """
        info = {"failed":[], "literals": {}}
        res = bool(self.eval(pred, document, info))
        return res, info

    def eval(self, pred, doc, info=None):
        "Node-specific implementation"
        return True


class LogicalOperator(Node):
    "Used for the logical operators"
    def __init__(self, op, left, right):
        self.type = op
        self.left = left
        self.right = right

    def name(self):
        return "%s operator at %s" % (self.type.upper(), self.position)

    def _validate(self, info):
        "Validates the node"
        if self.type not in ("and", "or"):
            errs = info["errors"]
            errs.append("Unknown logical operator %s" % self.type)
            return False
        return True

    @failure_info
    def eval(self, pred, doc, info=None):
        "Implement short-circuit logic"
        if self.type == "and":
            if not self.left.eval(pred, doc, info):
                return False
            if not self.right.eval(pred, doc, info):
                return False
            return True
        else:
            if self.left.eval(pred, doc, info):
                return True
            if self.right.eval(pred, doc, info):
                return True
            return False

    def failure_info(self, pred, doc, info):
        l = self.left.eval(pred, doc)
        if self.type == "and" and not l:
            err = "Left hand side of " + self.name() + " failed"
            info["failed"].append(err)
            return

        if self.type == "or":
            err = "Boths sides of " + self.name() + " failed"
        else:
            err = "Right hand side of " + self.name() + " failed"
        info["failed"].append(err)


class NegateOperator(Node):
    "Used to negate a result"
    def __init__(self, expr):
        self.left = expr

    def eval(self, pred, doc, info=None):
        return not self.left.eval(pred, doc, info)


class CompareOperator(Node):
    "Used for all the mathematical comparisons"
    def __init__(self, comparison, left, right):
        self.type = comparison
        self.left = left
        self.right = right

    def name(self):
        return "%s comparison at %s" % (self.type.upper(), self.position)

    def _validate(self, info):
        if self.type not in (">=", ">", "<", "<=", "=", "!=", "is"):
            errs = info["errors"]
            errs.append("Unknown compare operator %s" % self.type)
            return False
        return True

    @failure_info
    def eval(self, pred, doc, info=None):
        left = self.left.eval(pred, doc, info)
        right = self.right.eval(pred, doc, info)

        # Check if this is an equality check
        if self.type in ("=", "is"):
            return left == right
        elif self.type == "!=":
            return left != right

        # Compare operations against undefined or empty always fail
        if isinstance(left, (Undefined, Empty)):
            return False
        if isinstance(right, (Undefined, Empty)):
            return False

        if self.type == ">=":
            return left >= right
        elif self.type == ">":
            return left > right
        elif self.type == "<=":
            return left <= right
        elif self.type == "<":
            return left < right

    def failure_info(self, pred, doc, info):
        l = self.left.eval(pred, doc)
        r = self.right.eval(pred, doc)

        # Check if it was a failure due to undefined or empty
        if self.type not in ('=', '!=', 'is') and \
                isinstance(l, (Undefined, Empty)) or \
                isinstance(r, (Undefined, Empty)):
            err = self.name() + " failed with Undefined or Empty operand"
            info["failed"].append(err)
            return

        # Comparison failure
        err = self.name() + " failed, left: %s, right: %s" % \
                (repr(l), repr(r))
        info["failed"].append(err)


class ContainsOperator(Node):
    "Used for the 'contains' operator"
    def __init__(self, left, right):
        self.left = left
        self.right = right

    def _validate(self, info):
        if not isinstance(self.right, (Number, Literal, Constant)):
            errs = info["errors"]
            errs.append("Contains operator must take a literal or constant! Got: %s" % repr(self.right))
            return False
        return True

    @failure_info
    def eval(self, pred, doc, info=None):
        left = self.left.eval(pred, doc, info)
        right = self.right.eval(pred, doc, info)
        return right in left

    def failure_info(self, pred, doc, info):
        left = self.left.eval(pred, doc)
        right = self.right.eval(pred, doc)

        err = "Right side: %s not in left side: %s for %s" \
                % (repr(right), repr(left), self.name())
        info["failed"].append(err)


class MatchOperator(Node):
    "Used for the 'matches' operator"
    def __init__(self, left, right):
        self.left = left
        self.right = right

    def _validate(self, info):
        if not isinstance(self.right, Regex):
            errs = info["errors"]
            errs.append("Match operator must take a regex! Got: %s" % repr(self.right))
            return False
        return True

    @failure_info
    def eval(self, pred, doc, info=None):
        left = self.left.eval(pred, doc, info)
        if not isinstance(left, str):
            return False

        right = self.right.eval(pred, doc, info)
        match = right.search(left)
        return match is not None

    def failure_info(self, pred, doc, info):
        left = self.left.eval(pred, doc)
        re_str = self.right.value
        err = "Regex %s does not match %s for %s" % \
                (repr(re_str), repr(left), self.name())
        info["failed"].append(err)


class Regex(Node):
    "Regular expression literal"
    def __init__(self, value):
        # Unpack a Node object if we are given one
        if isinstance(value, Node):
            self.value = value.value.strip("'\"")
        else:
            self.value = value

    def _validate(self, info):
        if not isinstance(self.value, str):
            errs = info["errors"]
            errs.append("Regex must be a string! Got: %s" % repr(self.value))
            return False

        # Try to compile
        try:
            self.re = re.compile(self.value)
        except Exception, e:
            errs = info["errors"]
            errs.append("Regex compilation failed")
            regexes = info["regex"]
            regexes[self.value] = str(e)
            return False

        return True

    def eval(self, pred, doc, info=None):
        return self.re


class Literal(Node):
    "String literal"
    def __init__(self, value):
        self.value = value

    def name(self):
        return "Literal %s at %s" % (self.value, self.position)

    def eval(self, pred, doc, info=None):
        # Use the predicate class to resolve the identifier
        v = pred.resolve_identifier(doc, self.value)
        if info:
            info["literals"][self.value] = v
        return v


class Number(Node):
    "Numeric literal"
    def __init__(self, value):
        try:
            self.value = float(value)
        except:
            self.value = value

    def name(self):
        return "Number %f at %s" % (self.value, self.position)

    def _validate(self, info):
        if not isinstance(self.value, float):
            errs = info["errors"]
            errs.append("Failed to convert number to float! Got: %s" % self.value)
            return False
        return True

    def eval(self, pred, doc, info=None):
        return self.value


class Constant(Node):
    "Used for true, false, null"
    def __init__(self, value):
        self.value = value

    def name(self):
        return "Constant %s at %s" % (self.value, self.position)

    def _validate(self, info):
        if self.value not in (True, False, None):
            errs = info["errors"]
            errs.append("Invalid Constant! Got: %s" % self.value)
            return False
        return True

    def eval(self, pred, doc, info=None):
        return self.value


class Undefined(Node):
    "Represents a non-defined object"
    def __init__(self):
        return

    def __nonzero__(self):
        "Acts like False"
        return False

    def __eq__(self, other):
        "Only equal to undefined"
        return isinstance(other, Undefined)

    def eval(self, pred, doc, info=None):
        return False


class Empty(Node):
    "Represents the null set"
    def __init__(self):
        return

    def __nonzero__(self):
        "Acts like False"
        return False

    def __eq__(self, other):
        "Only equal to things of zero length"
        return len(other) == 0

    def eval(self, pred, doc, info=None):
        return False

