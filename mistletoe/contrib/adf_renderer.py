"""
Abstract syntax tree renderer for mistletoe.
"""

import json
from mistletoe import block_token
from mistletoe.base_renderer import BaseRenderer
from mistletoe.block_token import BlockToken, List, ListItem, ThematicBreak


def determine_list_type(token):
    if isinstance(token, List):
        return "orderedList" if getattr(token, "start") else "bulletList"
    return None


def determine_line_break(token):
    return None if getattr(token, "soft") else "hardBreak"


def determine_table_cell(token):
    return "tableHeader" if hasattr(token, "is_header") else "tableCell"


"""
    Determine the ADF type from the class type from AST.
    Some return functions to further determine which ADF
    type to return based on attributes of the AST token.
"""
ADF_TYPE = {
    "Document": "doc",
    "Heading": "heading",
    "RawText": "text",
    "Paragraph": "paragraph",
    "Emphasis": "em",
    "Strong": "strong",
    "Strikethrough": "strike",
    "LineBreak": determine_line_break,
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
    "TableCell": determine_table_cell,
    "SetextHeading": "heading",
    "ThematicBreak": "rule",
    "Quote": "blockquote",
    "AutoLink": "link",
    "EscapeSequence": None,
}

"""
AST attributes and the corresponding ADF attribute.
"""
ADF_ATTRS = {
    "level": "level",
    "target": "href",
    "title": "title",
    "language": "language",
}


"""
All mark nodes in ADF.
"""
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
    """
    Return a list containing ADF paragraph node to hold
    table cell or header contents.

    ADF handles tables differently from Mistletoe AST. Text
    can only be contained inside 'paragraph' nodes.

    Accepts:
        token: the table cell or table header token to be handled
    Returns:
        A list containing the paragraph node
    """
    paragraph_token = block_token.Paragraph([])
    paragraph_token.children = token.children
    return [paragraph_token]


def handle_marks(token, node, marks, parent_list):
    """
    If node is a ADF 'mark node', append to the list of marks
    and recursively step through to the next node.

    The marks list will be applied a non-block token node

    Accepts:
        token: the AST token to parse
        node: the dictionary containing ADF information
        marks: list of mark nodes
        parent_list: set which contains token[0] and node[1]
    """
    marks = [] if marks is None else marks
    marks.append(node)
    return get_adf(
        token.children[0],
        marks,
        blockquotes=node["type"] == "blockquote",
        parent_list=parent_list,
    )


def handle_children(token, node, marks, parent_list):
    """
    Handle the tokens children. Spawns new calls to `get_adf()`.
    Also handles some other edge cases, like if the current node
    is a blockquote or inside a list.

    Accepts:
        token: The AST token to parse
        node: the dictionary containing ADF information
        marks: list of mark nodes
        parent_list: set which contains token[0] and node[1]
    """

    if node["type"] == "tableCell" or node["type"] == "tableHeader":
        token.children = handle_table(token)

    for child in token.children:
        if ADF_TYPE[child.__class__.__name__]:
            node["content"] = (
                [] if node.get("content", None) is None else node["content"]
            )
            ret = get_adf(
                child,
                marks,
                blockquotes=node["type"] == "blockquote",
                parent_list=parent_list,
            )
            if ret["type"] is not None:
                node["content"].append(ret)

            # TODO find out way to remove or prevent the last empty paragraph from being
            #      added to the children/content lists. Current design adds extra empty
            #      paragraph at the end of nested loose lists.
            if (
                getattr(token, "loose", False)
                and isinstance(token, ListItem)
                and not isinstance(token.children[-1], ListItem)
            ):
                # For loose tables to render similar to markdown, we need to add
                # empty paragraphs at the end of a parent_list[0] content/children
                # Make a note that we have seen a paragraph node containing the text
                # This might need to be supported by other block token types as well,
                node["content"].append({"type": "paragraph", "content": []})

    if parent_list is not None and node["type"] == "blockquote":
        # blockquote nodes do not render inside of lists, so use its child
        # instead.
        node = get_adf(token.children[0], marks, parent_list=parent_list)


def process_node(token, node, marks, parent_list):
    if node["type"] == "doc":
        node["version"] = 1

    if "content" in vars(token) and node["type"] in TEXT_TYPE:
        node["text"] = getattr(token, "content").rstrip()

    for attrname in token.repr_attributes:
        if ADF_ATTRS.get(attrname, None) is not None:
            node["attrs"] = {} if node.get("attrs", None) is None else node["attrs"]
            node["attrs"][ADF_ATTRS[attrname]] = getattr(token, attrname)

    if node["type"] in MARK_VALUES:
        return handle_marks(token, node, marks, parent_list)

    if "header" in vars(token):
        # ADF has seperate header and table cell nodes. We need to generate
        # header nodes from the 'header' field.
        header_row_token = getattr(token, "header")
        for cell_token in header_row_token.children:
            cell_token.is_header = True

        token.children.insert(0, header_row_token)

    if token.__class__.__name__ == "SetextHeading":
        get_adf(ThematicBreak("---"))


def post_process_node(node, token, marks, blockquotes):
    if node.get("type", None) is None or (
        node.get("type", None) == "blockquote" and blockquotes
    ):
        # Handle two cases:
        # blockquotes can not be nested in ADF
        # nodes with 'None' type should be replaced with their children
        if len(node.get("content", [])) > 0:
            node = node.get("content", node)[0]
    if marks is not None and len(marks) > 0 and not isinstance(token, BlockToken):
        node["marks"] = marks


def get_adf(token, marks=None, blockquotes=False, parent_list=None):
    """
    Recursively unrolls token attributes into dictionaries (token.children
    into lists).

    Atlassian Document Format (ADF) defined here:
    developer.atlassian.com/cloud/jira/platform/apis/document/structure/

    Returns:
        a dictionary of token's attributes.
    """
    node = {}
    node["type"] = (
        (ADF_TYPE[token.__class__.__name__])(token)
        if callable(ADF_TYPE[token.__class__.__name__])
        else ADF_TYPE[token.__class__.__name__]
    )

    parent_list = (
        (token, node)
        if token.__class__.__name__ == "ListItem" and token.loose
        else parent_list
    )

    if node["type"] is not None and not blockquotes:
        ret = process_node(token, node, marks, parent_list)
        if ret:
            return ret

    if token.children is not None:
        handle_children(token, node, marks, parent_list)

    post_process_node(node, token, marks, blockquotes)

    return node
