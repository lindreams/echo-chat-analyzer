"""Invented conversation builders shared by sticker feature tests."""
from datetime import datetime, timedelta

from qq_chat_analyzer.analysis.timestamps import CHAT_TIMEZONE
from qq_chat_analyzer.rich_message import (
    ExpressionContent, RichMessage, SenderIdentity, StickerIdentity, TextContent,
)


def indexed(messages, *, positions=None, data=None, media=()):
    from qq_chat_analyzer.analysis.sticker_index import build_sticker_fact_index
    from qq_chat_analyzer.analysis.stickers import StickerData, collect_sticker_sends, count_sticker_messages

    if data is None:
        data = StickerData(collect_sticker_sends(messages), media=media,
                           message_counts=count_sticker_messages(messages))
    return build_sticker_fact_index(data, messages, source_positions=positions)


def formal_payload(rows, source, *, group=False):
    """Fictional Rich samples through the real QQ/WeChat adapter formats."""
    import hashlib
    from test_qq_db_rich_contents import _body, _sticker, _text
    from test_sticker_data import _private_payload

    if source == "qq":
        bodies = [_body(*(_text(p.text) if isinstance(p, TextContent) else
                           _sticker(p.sticker.identity_key.encode()) for p in m.contents)) for m in rows]
        payload = _private_payload(*bodies, senders=tuple("10001" if m.is_self else "20002" for m in rows))
        payload["self"] = {"namespace": "qq_uin", "value": "10001"}
        if group:
            payload["query"]["session_type"] = "group"
        for record, row in zip(payload["records"], rows):
            record["fields"]["40050"] = row.timestamp
        return payload
    assert source == "wechat"
    records = []
    for row in rows:
        if isinstance(row.contents[0], TextContent):
            records.append(dict(local_type=1, server_id="duplicate", create_time=row.timestamp,
                                user_name="fiction-self" if row.is_self else "fiction-peer",
                                message_content=row.contents[0].text))
        else:
            # Real type 47 has one sticker per record. Preserve author/time;
            # keep seconds distinct when the fictional Rich row has many sends.
            for i, part in enumerate(row.contents):
                digest = hashlib.md5(part.sticker.identity_key.encode()).hexdigest()
                records.append(dict(local_type=47, server_id="duplicate", create_time=row.timestamp+i,
                                    user_name="fiction-self" if row.is_self else "fiction-peer",
                                    message_content=f'<msg><emoji md5="{digest}"/></msg>'))
    return dict(source="wechat-db", conversation=dict(username="fiction-room",
                session_type="group" if group else "private", self_username="fiction-self"), messages=records)


class Messages:
    def __init__(self, name="fixture", start="2025-01-01"):
        self.name = name
        self.start = datetime.fromisoformat(start).replace(tzinfo=CHAT_TIMEZONE, hour=20)
        self.rows = []

    def add(self, day, side, *keys, text="", seconds=0):
        self.rows.append(RichMessage(
            message_id="duplicate", source="fiction", conversation_id=self.name,
            sender=SenderIdentity(f"fiction-{side}" if side else None, "同名"),
            timestamp=int((self.start+timedelta(days=day, seconds=seconds)).timestamp()),
            message_type="text", conversation_type="private",
            is_self=True if side == "A" else False if side == "B" else None,
            contents=tuple(([TextContent(text)] if text else []) + [ExpressionContent(
                "sticker", "display-does-not-identify", sticker=StickerIdentity(
                    "fictional", "fictional", f"fiction:{k}" if k is not None else None,
                )) for k in keys]),
        ))

    def ordered(self):
        # Only the fixture defines a chronological source. Production never
        # sorts input messages to hide an uncertain order.
        return tuple(sorted(self.rows, key=lambda m: m.timestamp))



def many_sticker_stories():
    """Independent fictional returns plus one relay and one shared habit."""
    b = Messages("visual-six-plus")
    for k, returned in enumerate((200, 400, 600, 800, 1000, 1200)):
        for day in (0, 2, 4, returned):
            b.add(day, "A", f"old{k}", seconds=k * 10)
    for day in (20, 40, 60):
        b.add(day, "A", "background")
    b.add(0, "B", text="虚构好友", seconds=900)
    for i in range(8):
        b.add(1210, "A" if i % 2 == 0 else "B", f"exchange{i % 3}", seconds=i * 20)
    for side in ("A", "B"):
        for day in (1215, 1217, 1219):
            b.add(day, side, "common", "common", seconds=100 + (side == "B") * 300)
    return b.ordered()
