from printer.schema.document import Document


def test_critical_styled_fields_carry_descriptions():
    """Live JSON Schema must annotate every styled enum so the MCP-delivered
    schema is self-documenting to agents."""
    schema = Document.model_json_schema()
    defs = schema["$defs"]

    expected = {
        ("HeaderBlock", "style"): "inverse_band",
        ("HeaderBlock", "subtitle"): "subtitle",
        ("SectionTitleBlock", "style"): "underline",
        ("ParagraphBlock", "emphasis"): "italic",
        ("LargeTextBlock", "size"): "xl",
        ("RichTextRun", "size"): "sm",
        ("RuleBlock", "style"): "solid",
        ("OrnamentBlock", "pattern"): "stars",
        ("QrBlock", "size"): "sm",
        ("QrBlock", "caption"): "caption",
        ("ImageBlock", "dither"): "atkinson",
        ("SpacerBlock", "lines"): "line",
        ("BulletsBlock", "marker"): "bullet",
    }
    for (cls_name, field), needle in expected.items():
        block = defs[cls_name]
        prop = block["properties"][field]
        desc = prop.get("description", "")
        assert needle in desc.lower(), (
            f"{cls_name}.{field} description should mention {needle!r}, got: {desc!r}"
        )
