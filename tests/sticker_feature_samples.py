"""Invented conversations; the seven reviewed V1.1 scenarios, without algorithms."""
from datetime import date, datetime, timedelta

from qq_chat_analyzer.analysis.timestamps import CHAT_TIMEZONE
from qq_chat_analyzer.rich_message import (
    ExpressionContent, RichMessage, SenderIdentity, StickerIdentity, TextContent,
)


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


def reviewed_scenarios():
    out = {}
    b = Messages("daily")
    for d in range(60):
        for i, text in enumerate(("今天还顺利吗？", "还行，晚点聊", "午饭吃什么？", "面条！")):
            b.add(d, "A" if i % 2 == 0 else "B", text=text, seconds=i*60)
        if d % 3 == 0:
            b.add(d, "A", "cat", seconds=400)
        if d % 4 == 0:
            b.add(d, "B", "tea", seconds=500)
    for d in (6, 13, 20, 27):
        b.add(d, "A", "thumb", seconds=700)
        b.add(d, "B", "thumb", seconds=780)
    b.add(2, "A", "penguin", seconds=900)
    for d in (16, 19, 23):
        b.add(d, "B", "penguin", seconds=900)
    for d in (45, 48, 51, 54, 57):
        b.add(d, "A", "duck", "duck", seconds=1000)
    out["daily"] = b.ordered()

    b = Messages("fighters", "2025-02-01")
    for d in range(14):
        b.add(d, "A", text="到家了吗？")
        b.add(d, "B", text="到了，今天累坏了", seconds=180)
        for i in range(8):
            b.add(d, "A" if i % 2 == 0 else "B",
                  ("cat", "panda", "goose", "thumb")[i % 4], seconds=600+i*35)
    b.add(6, "A", text="有本事别用文字，来！", seconds=3600)
    for i in range(12):
        b.add(6, "A" if i % 2 == 0 else "B", "panda", seconds=3620+i*12)
    b.add(6, "B", text="行行行，你赢了哈哈哈", seconds=3800)
    out["fighters"] = b.ordered()

    b = Messages("unequal", "2025-03-01")
    for d in range(120):
        for i in range(12):
            b.add(d, "A", text="虚构日常短句", seconds=i*20)
        for i in range(6):
            b.add(d, "A", f"图{(d*6+i)%40:02d}", seconds=600+i*20)
        if d % 6 == 0:
            b.add(d, "B", text="忙完了，看到啦", seconds=1800)
            b.add(d, "B", "cat", seconds=2000)
            b.add(d, "B", "cat" if d % 12 == 0 else "thumb", seconds=2100)
    out["unequal"] = b.ordered()

    b = Messages("short", "2025-06-10")
    for d in range(2):
        b.add(d, "A", text="今天的题好难")
        b.add(d, "B", text="我也是，脑子转不动了", seconds=60)
    b.add(0, "A", text="来，看看谁先认输", seconds=3600)
    for i in range(8):
        b.add(0, "A" if i % 2 == 0 else "B", "panda" if i < 4 else "goose", seconds=3620+i*15)
    b.add(0, "B", text="好吧，我先笑了", seconds=3760)
    out["short"] = b.ordered()

    b = Messages("old_friends", "2022-01-01")
    for d in range(0, 1460, 7):
        b.add(d, "A", text="这周过得怎么样？")
        b.add(d, "B", text="老样子，周末见", seconds=180)
        if d % 28 == 0:
            b.add(d, "A", "cat", seconds=400)
            b.add(d, "B", "tea", seconds=500)
    for i in range(100):
        b.add(400, "A", "goose", seconds=600+i)
    for dt in ("2023-01-01", "2023-01-05", "2023-01-10", "2023-08-15"):
        b.add((date.fromisoformat(dt)-date(2022, 1, 1)).days, "A", "bear", seconds=1000)
    out["old_friends"] = b.ordered()

    b = Messages("rich_steady")
    for d in range(180):
        for i in range(2):
            for side, shift in (("A", 0), ("B", 180)):
                b.add(d, side, f"轮换图{(d*2+i)%100:03d}", text="今天也平平常常", seconds=i*1800+shift)
    out["rich_steady"] = b.ordered()

    b = Messages("new_fad")
    for d in range(120):
        b.add(d, "A", text="今天打卡")
        b.add(d, "B", text="收到", seconds=60)
        if d % 2 == 0:
            b.add(d, "A", "cat", seconds=600)
    for d in (0, 30):
        b.add(d, "A", "duck", seconds=1000)
    for d in range(90, 100):
        for i in range(10):
            b.add(d, "A", "duck", seconds=1200+i)
    out["new_fad"] = b.ordered()
    return out
