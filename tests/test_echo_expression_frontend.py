"""Browser-behavior tests for the Echo expression culture chapter."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "frontend" / "echo_report" / "app.js"

NODE_RUNNER = r"""
const fs = require("fs");

class FakeNode {
  constructor(id, tag) {
    this.id = id || "";
    this.tagName = (tag || "").toUpperCase();
    this.textContent = "";
    this.hidden = false;
    this.children = [];
    this.className = "";
    this.style = { setProperty: function () {} };
    this.classList = { add: function () {} };
  }
  appendChild(child) { this.children.push(child); return child; }
}

function allText(node) {
  return [node.textContent].concat(node.children.map(allText)).join(" ").trim();
}

const ids = JSON.parse(process.env.ECHO_NODE_IDS);
const nodes = {};
ids.forEach(function (id) { nodes[id] = new FakeNode(id); });

global.window = {
  ECHO_DATA: JSON.parse(process.env.ECHO_PAYLOAD),
  ECHO_ASSETS: JSON.parse(process.env.ECHO_ASSETS || "{}")
};
global.document = {
  title: "",
  documentElement: new FakeNode("html"),
  getElementById: function (id) { return nodes[id] || null; },
  querySelectorAll: function () { return []; },
  createElement: function (tag) { return new FakeNode("", tag); }
};

eval(fs.readFileSync(process.env.ECHO_APP_PATH, "utf8"));

const result = {};
function toNode(node) {
  return {
    tag: node.tagName,
    src: node.src,
    className: node.className,
    text: node.textContent,
    children: (node.children || []).map(toNode)
  };
}
ids.forEach(function (id) {
  result[id] = {
    text: allText(nodes[id]),
    hidden: nodes[id].hidden,
    childCount: nodes[id].children.length,
    children: nodes[id].children.map(toNode)
  };
});
process.stdout.write(JSON.stringify(result));
"""


def _render(
    expression_culture: dict[str, object] | None,
    *,
    assets: dict[str, str] | None = None,
    language_profile: dict[str, object] | None = None,
) -> dict[str, object]:
    payload = {
        "conversation": {"kind": "group", "name": "虚构讨论组", "time_span": ""},
        "overview": {
            "has_data": True,
            "total_message_count": 3,
            "participant_count": 2,
            "empty_description": "",
        },
        "activity": {"hourly": [], "weekday": []},
        "conversation_sessions": None,
        "language_profile": language_profile,
        "expression_culture": expression_culture,
        "members": [],
    }
    environment = os.environ.copy()
    environment.update(
        {
            "ECHO_APP_PATH": str(APP_PATH),
            "ECHO_NODE_IDS": json.dumps(
                [
                    "expression",
                    "expression-toc",
                    "expression-intro",
                    "expression-message-count",
                    "expression-only-count",
                    "expression-unique-count",
                    "expression-top-list",
                    "expression-combos",
                    "expression-combo-list",
                    "expression-members",
                    "member-list",
                ]
            ),
            "ECHO_PAYLOAD": json.dumps(payload, ensure_ascii=False),
            "ECHO_ASSETS": json.dumps(assets or {}, ensure_ascii=True),
        }
    )
    completed = subprocess.run(
        ["node", "-e", NODE_RUNNER],
        check=True,
        capture_output=True,
        encoding="utf-8",
        env=environment,
    )
    return json.loads(completed.stdout)


def test_expression_chapter_renders_precomputed_culture() -> None:
    rendered = _render(
        {
            "available": True,
            "expression_message_count": 9,
            "expression_only_message_count": 2,
            "expression_only_rate": 0.22,
            "unique_expression_count": 4,
            "top_expressions": [
                {"display_text": "😀", "count": 5, "kind": "unicode"},
                {
                    "display_text": "[QQ表情 66]",
                    "count": 2,
                    "kind": "platform_face",
                    "with_text_message_count": 2,
                    "text_only_message_count": 0,
                },
            ],
            "members": [
                {
                    "speaker_key": "fictional-stable-key",
                    "display_name": "虚构 Alice",
                    "expression_occurrence_count": 5,
                    "expression_message_count": 4,
                    "expression_share_percent": 55.6,
                    "expression_only_message_count": 1,
                    "top_expressions": [
                        {
                            "display_text": "😀",
                            "count": 4,
                            "kind": "unicode",
                            "with_text_message_count": 4,
                            "text_only_message_count": 0,
                        }
                    ],
                }
            ],
        }
    )

    assert rendered["expression"]["hidden"] is False
    assert rendered["expression-toc"]["hidden"] is False
    assert "共同语言" in rendered["expression-intro"]["text"]
    assert "9 条" in rendered["expression-message-count"]["text"]
    assert "2 条" in rendered["expression-only-count"]["text"]
    assert "2 种" in rendered["expression-unique-count"]["text"]
    assert "😀" in rendered["expression-top-list"]["text"]
    assert "5 次" in rendered["expression-top-list"]["text"]
    assert "贴图" not in rendered["expression-top-list"]["text"]
    assert "带文字" not in rendered["expression-top-list"]["text"]
    assert "纯表情" not in rendered["expression-top-list"]["text"]
    assert "平台表情" not in rendered["expression-top-list"]["text"]
    assert "Unicode" not in rendered["expression-top-list"]["text"]
    assert "虚构 Alice" in rendered["expression-members"]["text"]
    assert "占全部表达" not in rendered["expression-members"]["text"]
    assert "带表达消息" not in rendered["expression-members"]["text"]
    assert "fictional-stable-key" not in rendered["expression-members"]["text"]
