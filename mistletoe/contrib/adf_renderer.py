"""
Abstract syntax tree renderer for mistletoe.
"""

import json
from mistletoe import block_token
from mistletoe.base_renderer import BaseRenderer
from mistletoe.block_token import BlockToken, ThematicBreak


def determine_list_type(token, node):
    if token.children:
        leader: str = getattr(token.children[0], "leader").replace(".", "")
        if leader.isdecimal():
            node["attrs"] = {}
            node["attrs"]["order"] = int(leader)
            return "orderedList"

    return "bulletList"


ADF_TYPE = {
    "Document": "doc",
    "Heading": "heading",
    "RawText": "text",
    "Paragraph": "paragraph",
    "Emphasis": "em",
    "Strong": "strong",
    "Strikethrough": "strike",
    "LineBreak": "hardBreak",
    "Link": "link",
    "InlineCode": "code",
    "CodeFence": "codeBlock",
    "BlockCode": "codeBlock",
    "List": determine_list_type,
    "ListItem": "listItem",
    "Image": None,  # ADF media tags require a page ID to generate its media ID.
    # Without it, they do not display properly.
    "Table": "table",
    "TableRow": "tableRow",
    "TableCell": lambda token, _: (
        "tableHeader" if hasattr(token, "is_header") else "tableCell"
    ),
    "SetextHeading": "heading",
    "ThematicBreak": "rule",
    "Quote": "blockquote",
    "AutoLink": "link",
    "EscapeSequence": None,
}

ADF_ATTRS = {
    "level": "level",
    "target": "href",
    "title": "title",
    "language": "language",
}
MARK_VALUES = ("em", "strong", "strike", "link", "code")
TEXT_TYPE = "text"


class AdfRenderer(BaseRenderer):
    def render(self, token):
        """
        Returns the string representation of the ADF.

        Overrides super().render. Delegates the logic to get_adf
        """
        return json.dumps(get_adf(token), indent=2) + "\n"

    def __getattr__(self, name):
        return lambda token: ""


def handle_table(token):
    paragraph_token = block_token.Paragraph([])
    paragraph_token.children = token.children
    return [paragraph_token]


def handle_marks(token, node, marks):
    marks = [] if marks is None else marks
    marks.append(node)
    return get_adf(token.children[0], marks, blockquotes=node["type"] == "blockquote")


def handle_children(token, node, marks):
    if token.__class__.__name__ == "SetextHeading":
        get_adf(ThematicBreak("---"))
    if node["type"] == "tableCell" or node["type"] == "tableHeader":
        token.children = handle_table(token)
    node["content"] = [
        get_adf(child, marks, blockquotes=node["type"] == "blockquote")
        for child in token.children
        if ADF_TYPE[child.__class__.__name__]
    ]


def process_node(token, node, marks):
    if node["type"] == "doc":
        node["version"] = 1

    if "content" in vars(token) and node["type"] in TEXT_TYPE:
        node["text"] = getattr(token, "content")
    for attrname in token.repr_attributes:
        if ADF_ATTRS.get(attrname, None) is not None:
            node["attrs"] = {} if node.get("attrs", None) is None else node["attrs"]
            node["attrs"][ADF_ATTRS[attrname]] = getattr(token, attrname)
    if node["type"] in MARK_VALUES:
        if node.get("attrs", None) is not None:
            if len(node["attrs"]) == 0:
                del node["attrs"]
        return handle_marks(token, node, marks)
    if "header" in vars(token):
        header_row_token = getattr(token, "header")
        for cell_token in header_row_token.children:
            cell_token.is_header = True

        token.children.insert(0, header_row_token)


def get_adf(token, marks=None, blockquotes=False):
    """
    Recursively unrolls token attributes into dictionaries (token.children
    into lists).

    Returns:
        a dictionary of token's attributes.
    """
    node = {}
    # Python 3.6 uses [ordered dicts] [1].
    # Put in 'type' entry first to make the final tree format somewhat
    # similar to [MDAST] [2].
    #
    #   [1]: https://docs.python.org/3/whatsNonenew/3.6.html
    #   [2]: https://github.com/syntax-tree/mdast
    node["type"] = (
        (ADF_TYPE[token.__class__.__name__])(token, node)
        if callable(ADF_TYPE[token.__class__.__name__])
        else ADF_TYPE[token.__class__.__name__]
    )

    if node["type"] is not None and not blockquotes:
        process_node(token, node, marks)

    if token.children is not None:
        handle_children(token, node, marks)

    if node.get("attrs", None) is not None:
        if len(node["attrs"]) == 0:
            del node["attrs"]
    if node.get("type", None) is None or (
        node.get("type", None) == "blockquote" and blockquotes
    ):
        node = node["content"][0]
    if marks is not None and len(marks) > 0 and not isinstance(token, BlockToken):
        node["marks"] = marks

    return node
