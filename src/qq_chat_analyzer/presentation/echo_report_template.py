"""Static templates for the self-contained Echo Report HTML output."""

from __future__ import annotations


ECHO_REPORT_HTML_SKELETON = r"""


<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>余音 Echo · 聊天记忆报告</title>
  __ECHO_FAVICON_TAG__
  <style>__ECHO_CSS__</style>
</head>
<body>
  <main class="report" aria-label="余音 Echo 聊天记忆报告">
    <section class="page cover" id="cover" aria-labelledby="cover-title">
      <div class="staff-lines" aria-hidden="true"></div>
      <header class="cover-brand">
        __ECHO_LOGO_TAG__
        <span class="edition">REPORT · 001</span>
      </header>

      <div class="cover-center">
        <p class="overline">聊天记忆报告</p>
        <h1 id="cover-title"></h1>
        <p class="cover-range" id="cover-range"></p>
        <p class="cover-note">重新阅读一段交流留下的痕迹。</p>
      </div>

      <footer class="cover-footer">
        <span>本地生成</span>
        <a href="#contents">开始阅读 <span aria-hidden="true">↓</span></a>
      </footer>
    </section>

    <section class="page contents" id="contents" aria-labelledby="contents-title">
      <header class="page-header">
        <p class="folio">CONTENTS</p>
        <h2 id="contents-title">目录</h2>
        <p>沿着时间与成员，重新看见这段交流。</p>
      </header>

      <nav class="toc" aria-label="报告目录">
        <a class="toc-row" href="#overview">
          <span class="toc-number">01</span>
          <span class="toc-copy"><strong>会话概览</strong><small>这段交流的基本轮廓</small></span>
          <span class="toc-leader" aria-hidden="true"></span>
          <span class="toc-page">03</span>
        </a>
        <a class="toc-row" id="session-toc" href="#conversation-sessions" hidden>
          <span class="toc-number">02</span>
          <span class="toc-copy"><strong>聊天轮次</strong><small>谁先开口，一次聊多久</small></span>
          <span class="toc-leader" aria-hidden="true"></span>
          <span class="toc-page">04</span>
        </a>
        <a class="toc-row" href="#rhythm">
          <span class="toc-number">03</span>
          <span class="toc-copy"><strong>节奏：活跃轨迹</strong><small>消息在时间中的落点</small></span>
          <span class="toc-leader" aria-hidden="true"></span>
          <span class="toc-page">05</span>
        </a>
        <a class="toc-row" href="#voices">
          <span class="toc-number">04</span>
          <span class="toc-copy"><strong>个人语言画像</strong><small>群聊特色词与私聊中的两种声音</small></span>
          <span class="toc-leader" aria-hidden="true"></span>
          <span class="toc-page">06</span>
        </a>
        <a class="toc-row" id="expression-toc" href="#expression" hidden>
          <span class="toc-number">05</span>
          <span class="toc-copy"><strong>表达文化</strong><small>表情与回应留下的共同语言</small></span>
          <span class="toc-leader" aria-hidden="true"></span>
          <span class="toc-page">07</span>
        </a>
        <a class="toc-row" id="sticker-toc" href="#stickers" hidden>
          <span class="toc-number">06</span>
          <span class="toc-copy"><strong>表情包</strong><small>查看表情包的发送次数与排行。</small></span>
          <span class="toc-leader" aria-hidden="true"></span>
          <span class="toc-page">08</span>
        </a>
        <div class="toc-row is-future">
          <span class="toc-number">07</span>
          <span class="toc-copy"><strong>互动关系</strong><small>未来章节</small></span>
          <span class="toc-leader" aria-hidden="true"></span>
          <span class="toc-page">—</span>
        </div>
        <div class="toc-row is-future">
          <span class="toc-number">08</span>
          <span class="toc-copy"><strong>余音</strong><small>让那些反复出现的词，成为最后的回响。</small></span>
          <span class="toc-leader" aria-hidden="true"></span>
          <span class="toc-page">—</span>
        </div>
      </nav>
      <span class="page-number">02</span>
    </section>

    <section class="page chapter" id="overview" aria-labelledby="overview-title">
      <header class="chapter-header">
        <span class="chapter-number">01</span>
        <div><p class="folio">OVERVIEW</p><h2 id="overview-title">会话概览</h2></div>
      </header>
      <p class="chapter-intro" id="overview-intro">一段交流的轮廓，从时间、消息与参与者开始。</p>

      <div class="overview-ledger">
        <div class="primary-figure">
          <span class="field-label">消息数量</span>
          <strong id="overview-message-count"></strong>
          <span class="field-unit">条消息</span>
        </div>
        <dl class="archive-fields">
          <div><dt>时间跨度</dt><dd id="overview-time-span"></dd><small>报告覆盖的时间范围</small></div>
          <div><dt>参与人数</dt><dd id="overview-participants"></dd><small>在这段会话中留下消息</small></div>
          <div><dt>活跃天数</dt><dd id="overview-active-days"></dd><small>实际有聊天的日子</small></div>
          <div><dt>日均消息</dt><dd id="overview-average-per-day"></dd><small>有聊天的日子平均消息数</small></div>
          <div class="wide"><dt>最活跃时间</dt><dd id="busiest-hour"></dd><small>一天中消息最集中的时段</small></div>
        </dl>
      </div>
      <span class="page-number">03</span>
    </section>

    <section class="page chapter session-chapter" id="conversation-sessions" aria-labelledby="sessions-title" hidden>
      <header class="chapter-header">
        <span class="chapter-number">02</span>
        <div><p class="folio">SESSIONS</p><h2 id="sessions-title">聊天轮次</h2></div>
      </header>
      <p class="chapter-intro" id="session-lead"></p>
      <p class="session-viewer-identity" id="session-viewer-identity" hidden></p>

      <!-- 谁来起拍 -->
      <div class="session-movement" id="session-beat" hidden>
        <h3 class="movement-heading"><span class="movement-icon" aria-hidden="true"></span><span id="session-beat-title">谁来起拍</span></h3>
        <p class="session-beat-lead" id="session-group-top"></p>
        <p class="peak-hour-note" id="session-peak-hour" hidden></p>
        <p class="peak-hour-note" id="session-self-peak-hour" hidden></p>
        <p class="peak-hour-note" id="session-peer-peak-hour" hidden></p>
      </div>

      <!-- 接住第一句话 -->
      <div class="session-movement" id="session-reply" hidden>
        <h3 class="movement-heading"><span class="movement-icon" aria-hidden="true"></span><span id="session-reply-title">接住第一句话</span></h3>
        <dl class="session-fields">
          <div><dt>你开口之后</dt><dd id="session-reply-self-to-peer"></dd><small>TA 通常接住第一句</small></div>
          <div><dt>TA 开口之后</dt><dd id="session-reply-peer-to-self"></dd><small>你通常接住第一句</small></div>
        </dl>
      </div>

      <!-- 一段乐句 -->
      <div class="session-movement" id="session-movement" hidden>
        <h3 class="movement-heading"><span class="movement-icon" aria-hidden="true"></span>一段乐句</h3>
        <dl class="session-fields">
          <div><dt>通常会聊多久</dt><dd id="session-median-duration"></dd><small>所有聊天轮次的中位时长</small></div>
          <div><dt>平均每轮消息</dt><dd id="session-average-messages"></dd><small>平均每轮留下的消息数量</small></div>
        </dl>
        <p class="session-character" id="session-character" hidden></p>
      </div>

      <!-- 聊天里的几个高音 -->
      <div class="session-movement" id="session-highnotes" hidden>
        <h3 class="movement-heading"><span class="movement-icon" aria-hidden="true"></span><span id="session-highnotes-title">聊天里的几个高音</span></h3>
        <div class="highnote-grid">
          <div class="highnote-card" id="session-loudest-messages" hidden>
            <span class="highnote-badge"><span class="highnote-note" aria-hidden="true">♪</span>话最多</span>
            <span class="highnote-stat" id="session-loudest-messages-text"></span>
            <span class="highnote-time" id="session-loudest-messages-time"></span>
          </div>
          <div class="highnote-card" id="session-loudest-duration" hidden>
            <span class="highnote-badge"><span class="highnote-note" aria-hidden="true">𝅝</span>聊最久</span>
            <span class="highnote-stat" id="session-loudest-duration-text"></span>
            <span class="highnote-time" id="session-loudest-duration-time"></span>
          </div>
          <div class="highnote-card" id="session-loudest-participants" hidden>
            <span class="highnote-badge"><span class="highnote-note" aria-hidden="true">♫</span>最热闹</span>
            <span class="highnote-stat" id="session-loudest-participants-text"></span>
            <span class="highnote-time" id="session-loudest-participants-time"></span>
          </div>
          <div class="highnote-card" id="session-loudest-densest" hidden>
            <span class="highnote-badge"><span class="highnote-note" aria-hidden="true">♬</span>接得最紧</span>
            <span class="highnote-stat" id="session-loudest-densest-text"></span>
            <span class="highnote-time" id="session-loudest-densest-time"></span>
          </div>
          <div class="highnote-card" id="session-loudest-back-and-forth" hidden>
            <span class="highnote-badge"><span class="highnote-note" aria-hidden="true">♫</span>最有来有回</span>
            <span class="highnote-stat" id="session-loudest-back-and-forth-text"></span>
            <span class="highnote-time" id="session-loudest-back-and-forth-time"></span>
          </div>
        </div>
      </div>

      <!-- 休止 -->
      <p class="session-rest-note" id="session-rest" hidden>
        <span class="session-rest-symbol" aria-hidden="true">𝄽</span> 休止 · <span id="session-threshold-note"></span>
      </p>
      <span class="page-number">04</span>
    </section>

    <section class="page chapter" id="rhythm" aria-labelledby="rhythm-title">
      <header class="chapter-header">
        <span class="chapter-number">03</span>
        <div><p class="folio">RHYTHM</p><h2 id="rhythm-title">节奏</h2></div>
      </header>
      <p class="chapter-intro">消息在一天与一周中的分布，形成这段交流的时间纹理。</p>

      <figure class="figure-block">
        <figcaption><h3>一天中的活跃轨迹</h3><p>每一格代表一个小时，深浅仅表示消息数量。</p></figcaption>
        <div class="hourly-track" role="img" aria-label="全天二十四小时活跃分布">
          <div class="staff-grid" aria-hidden="true"></div>
          <div class="hour-bars" id="hour-bars" aria-hidden="true"></div>
          <div class="hour-labels"><span>00</span><span>06</span><span>12</span><span>18</span><span>23</span></div>
        </div>
      </figure>

      <figure class="figure-block weekday-figure">
        <figcaption><h3>一周中的活跃轨迹</h3><p>星期顺序保持不变，便于阅读时间节奏。</p></figcaption>
        <div class="weekday-tracks" id="weekday-tracks" role="img" aria-label="星期一到星期日活跃分布"></div>
      </figure>
      <span class="page-number">05</span>
    </section>

    <section class="page chapter" id="voices" aria-labelledby="voices-title">
      <header class="chapter-header">
        <span class="chapter-number">04</span>
        <div><p class="folio">VOICES</p><h2 id="voices-title">语言画像</h2></div>
      </header>
      <p class="chapter-intro" id="voices-intro"></p>

      <div class="member-list" id="member-list"></div>
      <div class="private-language-blocks" id="private-shared-words" hidden>
        <h3>同频</h3>
        <p>两个人都相对常说的词。</p>
        <ul class="language-word-list" id="private-shared-words-list"></ul>
      </div>
      <div class="private-language-blocks" id="private-side-words" hidden>
        <h3>谁更常这样说</h3>
        <p>同一份习惯里，更常开口的一方。</p>
        <ul class="language-word-list" id="private-side-words-list"></ul>
      </div>
      <span class="page-number">06</span>
    </section>

    <section class="page chapter expression-chapter" id="expression" aria-labelledby="expression-title" hidden>
      <header class="chapter-header">
        <span class="chapter-number">05</span>
        <div><p class="folio">EXPRESSIONS</p><h2 id="expression-title">表达文化</h2></div>
      </header>
      <p class="chapter-intro" id="expression-intro"></p>

      <dl class="expression-fields">
        <div><dt>带表达的消息</dt><dd id="expression-message-count"></dd><small>包含表达的消息数</small></div>
        <div><dt>只用表达回应</dt><dd id="expression-only-count"></dd><small>只用表达、没有文字</small></div>
        <div><dt>常用表达</dt><dd id="expression-unique-count"></dd><small>当前展示的常用表达数量</small></div>
      </dl>

      <div class="expression-top">
        <h3>这段交流最常用的表达</h3>
        <ul class="expression-list" id="expression-top-list"></ul>
      </div>
      <div class="expression-combos" id="expression-combos" hidden>
        <h3>常一起出现的表达</h3>
        <ul class="expression-combo-list" id="expression-combo-list"></ul>
      </div>
      <div class="expression-members" id="expression-members"></div>
      <span class="page-number">07</span>
    </section>

    <section class="page chapter sticker-chapter" id="stickers" aria-labelledby="sticker-title" hidden>
      <header class="chapter-header">
        <span class="chapter-number">06</span>
        <div><p class="folio">STICKERS</p><h2 id="sticker-title">表情包</h2></div>
      </header>
      <p class="chapter-intro">有些回应，交给一张图。</p>
      <dl class="sticker-fields" id="sticker-fields">
        <div><dt>表情包发送</dt><dd id="sticker-total"></dd></div>
        <div><dt>使用过</dt><dd id="sticker-unique"></dd></div>
      </dl>
      <p class="sticker-empty" id="sticker-empty" hidden></p>
      <div class="sticker-group-rankings" id="sticker-group-rankings" hidden></div>
      <div id="sticker-rankings">
        <div class="sticker-section-heading" id="sticker-personal-heading"><h3>成员最常用</h3></div>
        <details id="sticker-member-picker" hidden>
          <summary id="sticker-member-summary">选择成员</summary>
          <input id="sticker-member-search" type="search" aria-label="搜索成员" placeholder="搜索成员" autocomplete="off">
          <div id="sticker-member-options" role="group" aria-label="选择要比较的成员"></div>
        </details>
        <div class="sticker-members" id="sticker-members"></div>
      </div>
      <div class="sticker-dynamic" id="sticker-dynamic" hidden>
        <div id="sticker-shared" hidden>
          <h3 id="sticker-shared-title">我们共同最常用</h3>
          <div id="sticker-shared-list"></div>
        </div>
      </div>
      <span class="page-number">08</span>
    </section>

    <section class="page future" id="future" aria-labelledby="future-title">
      <header class="page-header"><p class="folio">UNWRITTEN</p><h2 id="future-title">尚未展开的部分</h2><p>有些痕迹，将在之后的章节中继续被看见。</p></header>
      <div class="future-list">
        <div><span>07</span><h3>互动关系</h3><p>交流方向与回应方式。</p></div>
        <div><span>08</span><h3>余音</h3><p>未来将以聊天词云，为 Echo Report 留下最后的回响。</p></div>
      </div>
      <footer class="end-mark"><a href="#cover">回到封面 ↑</a><span>余音 Echo · <b data-current-year>2026</b></span></footer>
      <span class="page-number">09</span>
    </section>
  </main>



  <script>
window.ECHO_DATA = __ECHO_DATA__;
  window.ECHO_ASSETS = __ECHO_ASSETS__;
  </script>
  <script>__ECHO_APP_JS__</script>


</body>
</html>

"""


ECHO_REPORT_CSS = r"""
:root {
  --paper: #f3efe6;
  --paper-light: #faf7f0;
  --canvas: #d8d2c8;
  --ink: #292720;
  --muted: #716b61;
  --faint: #aaa398;
  --rule: #d2cabd;
  --accent: #9b5b45;
  --accent-soft: #dfc6b8;
  --viewer: #527066;
  --viewer-soft: #e2ebe5;
  --serif: "Noto Serif SC", "Source Han Serif SC", "Songti SC", SimSun, serif;
  --sans: "Noto Sans SC", "Microsoft YaHei", system-ui, sans-serif;
  --music: "Segoe UI Symbol", "Noto Sans Symbols 2", "Noto Music", "DejaVu Sans", sans-serif;
}

* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin: 0; color: var(--ink); background: var(--canvas); font-family: var(--sans); }
a { color: inherit; text-decoration: none; }

.report { width: min(100% - 32px, 1040px); margin: 32px auto 80px; }
.page { position: relative; min-height: 980px; margin-bottom: 28px; padding: clamp(48px, 8vw, 92px); overflow: hidden; background: var(--paper); box-shadow: 0 14px 44px rgb(53 45 36 / 10%); }
.page-number { position: absolute; right: 42px; bottom: 32px; color: var(--faint); font: 12px/1 var(--serif); letter-spacing: .16em; }
.folio, .overline { margin: 0 0 12px; color: var(--accent); font: 600 11px/1.4 var(--sans); letter-spacing: .2em; text-transform: uppercase; }
h1, h2, h3, dd, strong { font-family: var(--serif); }
h1, h2, h3, p { margin-top: 0; }

.cover { display: flex; min-height: calc(100vh - 64px); flex-direction: column; justify-content: space-between; }
.cover-brand, .cover-footer { position: relative; z-index: 1; display: flex; align-items: center; justify-content: space-between; color: var(--muted); font-size: 12px; letter-spacing: .12em; }
.brand-logo { display: block; height: 34px; width: auto; }
.brand-name { color: var(--ink); font-family: var(--serif); font-size: 17px; letter-spacing: .08em; }
.cover-center { position: relative; z-index: 1; width: min(100%, 700px); margin: auto 0; padding: 10vh 0 7vh; }
.cover h1 { max-width: 780px; margin: 18px 0 22px; font-size: clamp(46px, 8vw, 86px); font-weight: 500; line-height: 1.14; letter-spacing: -.035em; }
.cover-range { color: var(--muted); font: 14px/1.7 var(--serif); letter-spacing: .1em; }
.cover-note { max-width: 360px; margin-top: 58px; color: var(--muted); font: 18px/1.9 var(--serif); }
.cover-footer a { padding-bottom: 5px; border-bottom: 1px solid var(--accent); color: var(--accent); }
.staff-lines { position: absolute; top: 38%; right: -12%; width: 76%; height: 92px; opacity: .62; background: repeating-linear-gradient(to bottom, transparent 0 17px, var(--rule) 17px 18px); transform: rotate(-2deg); }

.page-header { max-width: 620px; padding-bottom: 34px; border-bottom: 1px solid var(--rule); }
.page-header h2, .chapter-header h2 { margin: 0; font-size: clamp(36px, 6vw, 60px); font-weight: 500; line-height: 1.2; }
.page-header > p:last-child { margin: 22px 0 0; color: var(--muted); line-height: 1.8; }
.toc { margin-top: 64px; }
.toc-row { display: grid; grid-template-columns: 44px minmax(180px, auto) 1fr 30px; gap: 18px; align-items: end; padding: 18px 0; border-bottom: 1px solid rgb(210 202 189 / 55%); }
.toc-number { color: var(--accent); font: 15px/1 var(--serif); }
.toc-copy { display: flex; flex-direction: column; gap: 6px; }
.toc-copy strong { font-size: 20px; font-weight: 500; }
.toc-copy small { color: var(--muted); font-size: 12px; }
.toc-leader { height: 1px; margin-bottom: 5px; background-image: radial-gradient(circle, var(--faint) 1px, transparent 1px); background-position: bottom; background-size: 6px 2px; background-repeat: repeat-x; }
.toc-page { color: var(--muted); font: 12px/1 var(--serif); text-align: right; }
.is-future { color: var(--faint); }
.is-future .toc-number, .is-future .toc-copy small { color: var(--faint); }

.chapter-header { display: flex; gap: 26px; align-items: flex-start; padding-bottom: 24px; border-bottom: 1px solid var(--rule); }
.chapter-number { padding-top: 9px; color: var(--accent); font: 16px/1 var(--serif); letter-spacing: .08em; }
.chapter-intro { max-width: 540px; margin: 32px 0 62px; color: var(--muted); font: 17px/2 var(--serif); }
.session-chapter .chapter-intro { margin: 0 0 40px; }
.overview-ledger { border-top: 1px solid var(--ink); border-bottom: 1px solid var(--ink); }
.primary-figure { display: grid; grid-template-columns: 1fr auto; align-items: end; min-height: 250px; padding: 42px 0; border-bottom: 1px solid var(--rule); }
.primary-figure strong { font-size: clamp(72px, 13vw, 132px); font-weight: 400; line-height: .9; letter-spacing: -.06em; }
.field-label, .field-unit { color: var(--muted); font-size: 13px; letter-spacing: .08em; }
.field-unit { grid-column: 2; margin-top: 14px; text-align: right; }
.archive-fields { display: grid; grid-template-columns: 1fr 1fr; margin: 0; }
.archive-fields div { min-height: 150px; padding: 28px 0; }
.archive-fields div:nth-child(odd) { padding-right: 34px; border-right: 1px solid var(--rule); }
.archive-fields div:nth-child(even) { padding-left: 34px; }
.archive-fields .wide { grid-column: 1 / -1; padding-right: 0; border-top: 1px solid var(--rule); border-right: 0; }
.archive-fields dt, .member-entry dt { color: var(--muted); font-size: 12px; letter-spacing: .08em; }
.archive-fields dd { margin: 18px 0 7px; font-size: 29px; }
.archive-fields small { color: var(--faint); }

.session-fields { display: grid; grid-template-columns: 1fr 1fr; margin: 0; }
.session-fields[hidden] { display: none; }
.session-fields div { min-height: 150px; padding: 28px 0; }
.session-fields div:nth-child(odd) { padding-right: 34px; border-right: 1px solid var(--rule); }
.session-fields div:nth-child(even) { padding-left: 34px; }
.session-fields dt { color: var(--muted); font-size: 12px; letter-spacing: .08em; }
.session-fields dd { margin: 18px 0 7px; font-size: 25px; }
.session-fields small { color: var(--faint); font-size: 12px; }
.session-rest-note {
  margin: 48px 0 0;
  color: var(--faint);
  font: 12px/1.8 var(--sans);
  letter-spacing: 0.02em;
  text-align: right;
}

.session-rest-symbol {
  font-family: var(--music);
  font-size: 13px;
}

.figure-block { margin: 0 0 72px; }
.figure-block figcaption { display: flex; align-items: baseline; justify-content: space-between; gap: 24px; margin-bottom: 26px; }
.figure-block h3 { margin: 0; font-size: 21px; font-weight: 500; }
.figure-block figcaption p { margin: 0; color: var(--muted); font-size: 12px; }
.hourly-track { position: relative; height: 230px; padding: 24px 0 28px; border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); }
.staff-grid { position: absolute; inset: 28px 0 40px; background: repeating-linear-gradient(to bottom, transparent 0 31px, rgb(210 202 189 / 72%) 31px 32px); }
.hour-bars { position: absolute; inset: 30px 0 41px; display: grid; grid-template-columns: repeat(24, 1fr); gap: clamp(3px, .8vw, 8px); align-items: end; }
.hour-bars i { height: calc(var(--v) * 1%); min-height: 3px; background: var(--accent-soft); border-radius: 1px 1px 0 0; }
.hour-bars i.peak { background: var(--accent); }
.hour-labels { position: absolute; right: 0; bottom: 11px; left: 0; display: flex; justify-content: space-between; color: var(--muted); font: 10px/1 var(--sans); }
.weekday-tracks { padding: 6px 0; border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); }
.weekday-tracks > div { display: grid; grid-template-columns: 48px 1fr 36px; gap: 18px; align-items: center; min-height: 46px; border-bottom: 1px solid rgb(210 202 189 / 55%); }
.weekday-tracks > div:last-child { border-bottom: 0; }
.weekday-tracks span, .weekday-tracks em { color: var(--muted); font-size: 12px; font-style: normal; }
.weekday-tracks em { text-align: right; }
.weekday-tracks b { position: relative; height: 5px; background: #e5ded2; }
.weekday-tracks i { position: absolute; inset: 0 auto 0 0; width: var(--v); background: var(--accent); }

.member-list { border-top: 1px solid var(--ink); }
.member-list.mode-private { display: grid; grid-template-columns: 1fr 1fr; }
/* A big group lists every member in full. The section keeps the report's
   book-page height and lets the portraits continue below it, so one group's
   list can never push the rest of the chapter off the page.
   On a wide screen the portraits sit in two compact columns, so one screen
   shows six voices instead of two. */
.member-list.mode-group {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  column-gap: 44px;
  max-height: min(560px, 72vh);
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-width: thin;
  scrollbar-color: var(--accent-soft) transparent;
}
.member-list.mode-group::-webkit-scrollbar { width: 8px; }
.member-list.mode-group::-webkit-scrollbar-track { background: transparent; }
.member-list.mode-group::-webkit-scrollbar-thumb {
  border-radius: 4px;
  background: var(--accent-soft);
}
.member-list.mode-group::-webkit-scrollbar-thumb:hover { background: var(--accent); }
.voice-entry { position: relative; min-width: 0; padding: 34px 0 42px; border-bottom: 1px solid var(--rule); }
.mode-private .voice-entry { min-height: 340px; padding-right: 34px; }
.mode-private .voice-entry + .voice-entry { padding-right: 0; padding-left: 34px; border-left: 1px solid var(--rule); }
.voice-entry header { display: flex; flex-wrap: wrap; align-items: baseline; gap: 18px; }
.voice-entry h3 { min-width: 0; margin: 0; overflow-wrap: anywhere; font: 500 25px/1.3 var(--sans); }
.member-index { color: var(--accent); font: 13px/1.8 var(--serif); }
.voice-descriptor { margin: 13px 0 0 40px; color: var(--muted); font: 14px/1.8 var(--serif); overflow-wrap: anywhere; }
.voice-words { display: flex; flex-wrap: wrap; min-width: 0; gap: 12px 28px; margin: 34px 0 0 40px; padding: 0; list-style: none; }
.voice-words li { position: relative; min-width: 0; max-width: 100%; overflow-wrap: anywhere; color: var(--ink); font: 400 clamp(25px, 4vw, 39px)/1.25 var(--serif); letter-spacing: -.02em; }
.voice-word-token {
  display: inline-flex;
  min-height: 1.12em;
  max-width: 100%;
  overflow-wrap: anywhere;
  align-items: center;
  line-height: 1;
  vertical-align: middle;
}
.voice-word-token .voice-expression {
  display: block;
  width: 1.28em;
  height: 1.28em;
  flex: 0 0 1.28em;
  margin-right: 0;
  object-fit: contain;
  vertical-align: middle;
}
.voice-words li::after { margin-left: 28px; color: var(--accent-soft); content: "／"; font-size: .56em; vertical-align: .18em; }
.voice-words li:last-child::after { content: ""; }
.mode-private .voice-words {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 24px;
  margin-top: 42px;
}
.mode-private .voice-words li { margin: 0; font-size: 30px; }
.mode-private .voice-words li::after { content: ""; }
.voice-context { margin: 30px 0 0 40px; color: var(--faint); font: 13px/1.8 var(--serif); overflow-wrap: anywhere; }
/* Group portraits stay compact so one screen shows six voices: five words share
   one line, and the statistics line keeps its place under them. */
.member-list.mode-group .voice-entry { padding: 20px 0 18px; }
.member-list.mode-group .voice-entry header { gap: 12px; }
.member-list.mode-group .voice-entry h3 { font: 500 18px/1.35 var(--sans); }
.member-list.mode-group .member-index { font-size: 11px; }
.member-list.mode-group .voice-descriptor { margin: 6px 0 0; font-size: 12.5px; line-height: 1.6; }
.member-list.mode-group .voice-words { gap: 6px 7px; margin: 11px 0 0; }
.member-list.mode-group .voice-words li { font: 400 20px/1.3 var(--serif); letter-spacing: 0; }
.member-list.mode-group .voice-words li::after { margin-left: 7px; font-size: .5em; }
.member-list.mode-group .voice-context { margin: 9px 0 0; font: 12px/1.7 var(--serif); }
.language-unavailable { margin: 0; padding: 52px 0; color: var(--muted); font: 17px/2 var(--serif); border-bottom: 1px solid var(--rule); }

.private-language-blocks {
  margin-top: 36px;
  padding-top: 24px;
  border-top: 1px solid var(--rule);
}

.private-language-blocks h3 {
  margin: 0 0 12px;
  font-size: 21px;
  font-weight: 500;
}

.private-language-blocks > p {
  margin: 0 0 18px;
  color: var(--muted);
  font: 14px/1.8 var(--serif);
}

.language-word-list {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 28px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.language-word-list li {
  color: var(--ink);
  font: 400 22px/1.4 var(--serif);
}

.sticker-chapter { overflow: visible; }
.sticker-chapter [hidden] { display: none !important; }
.sticker-chapter .chapter-intro { margin: 10px 0 14px; }
.sticker-group-rankings { display: grid; grid-template-columns: 1fr 1fr; gap: 28px; border-bottom: 1px solid var(--rule); padding-bottom: 16px; margin-bottom: 16px; }
.sticker-group-rankings h4 { margin: 0 0 10px; font: 18px var(--serif); }
.sticker-group .sticker-members { grid-template-columns: 1fr; }
#sticker-member-picker { margin-bottom: 20px; font-size: 13px; color: var(--muted); }
#sticker-member-picker summary { cursor: pointer; color: var(--accent); }
#sticker-member-search { box-sizing: border-box; width: 100%; margin: 12px 0 8px; padding: 8px 10px; background: var(--paper); color: var(--ink); border: 1px solid var(--rule); font: inherit; }
#sticker-member-options { max-height: 180px; overflow-y: auto; display: grid; grid-template-columns: 1fr 1fr; gap: 6px 16px; }
#sticker-member-options label { display: flex; align-items: center; gap: 8px; padding: 6px 0; cursor: pointer; overflow-wrap: anywhere; }
#sticker-member-options input { accent-color: var(--accent); }
.sticker-expand { background: none; border: 0; border-bottom: 1px solid var(--rule); color: var(--accent); font: 12px var(--sans); padding: 4px 0; margin-top: 8px; cursor: pointer; }
.sticker-detail { color: var(--muted); font-size: 10px; line-height: 1.6; display: block; margin-top: 4px; }
.sticker-fields { display: grid; grid-template-columns: 1fr 1fr; margin: 0 0 18px; border-bottom: 1px solid var(--rule); }
.sticker-fields > div { padding: 0 0 14px; }
.sticker-fields dt { color: var(--muted); font-size: 13px; }
.sticker-fields dd { margin: 6px 0 0; font-size: 28px; line-height: 1.2; }
.sticker-section-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.sticker-section-heading h3, .sticker-dynamic h3 { margin: 0; font-size: 20px; font-weight: 500; }
.sticker-section-heading small { color: var(--muted); font-size: 12px; }
.sticker-members { display: grid; grid-template-columns: 1fr 1fr; gap: 28px; }
.sticker-member { min-width: 0; }
.sticker-member + .sticker-member { border-left: 1px solid var(--rule); padding-left: 28px; }
.sticker-group .sticker-member + .sticker-member { border-left: 0; padding-left: 0; border-top: 1px solid var(--rule); padding-top: 20px; }
.sticker-member h4 { margin: 0 0 6px; font: 500 20px/1.3 var(--serif); overflow-wrap: anywhere; }
.sticker-member h4 strong { color: var(--accent); font-weight: 400; }
.sticker-rate { color: var(--muted); font-size: 12px; margin: 0 0 12px; }
.sticker-top-list { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px 12px; margin: 0; padding: 0; list-style: none; }
.sticker-top-list li { min-width: 0; display: flex; flex-direction: column; align-items: flex-start; }
#sticker-shared-list .sticker-top-list { max-width: 560px; }
.sticker-image { position: relative; display: grid; place-items: center; width: 100%; aspect-ratio: 1; background: var(--canvas); color: var(--faint); }
.sticker-placeholder { font: 12px/1.4 var(--sans); }
.sticker-image.has-image .sticker-placeholder { display: none; }
.sticker-image img { position: absolute; width: 100%; height: 100%; object-fit: contain; }
.sticker-rank { display: block; color: var(--muted); font: 12px/1 var(--serif); margin-bottom: 6px; }
.sticker-count { display: block; margin-top: 6px; font: 18px/1.3 var(--serif); }
.sticker-preview { display: block; font-size: 10px; color: var(--muted); margin-top: 3px; }
.sticker-member-empty, .sticker-empty { color: var(--muted); font: 14px/1.8 var(--serif); }
.sticker-empty { margin: 36px 0; }
.sticker-dynamic { display: flex; gap: 32px; border-top: 1px solid var(--rule); margin-top: 22px; padding-top: 16px; }
.sticker-dynamic[hidden] { display: none; }
.sticker-dynamic > div { flex: 1; min-width: 0; }
.sticker-dynamic h3 { font-size: 17px; margin-bottom: 10px; }
@media (min-width: 721px) {
  .sticker-chapter { padding: 44px 82px 64px; }
  .sticker-chapter .chapter-header { padding-bottom: 16px; }
  .sticker-chapter .chapter-header h2 { font-size: 52px; }
  .sticker-chapter .chapter-intro { margin: 6px 0 10px; }
  .sticker-fields { margin-bottom: 12px; }
  .sticker-top-list { grid-template-columns: repeat(3, minmax(0, 120px)); }
  .sticker-group-rankings:has(> .is-expanded) { grid-template-columns: 1fr; }
  .sticker-group-rankings > .is-expanded { order: -1; }
  .sticker-members:has(> .is-expanded) { grid-template-columns: 1fr; }
  .sticker-members:has(> .is-expanded) > .sticker-member + .sticker-member { border-left: 0; padding-left: 0; border-top: 1px solid var(--rule); padding-top: 20px; }
  .sticker-group .sticker-member .sticker-top-list,
  .sticker-members:has(> .is-expanded) .sticker-top-list,
  .sticker-group-rankings:has(> .is-expanded) .sticker-top-list { grid-template-columns: repeat(5, minmax(0, 120px)); }
}

.expression-chapter .chapter-intro { margin: 0 0 44px; }
.expression-fields {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  margin: 0;
  border-top: 1px solid var(--ink);
  border-bottom: 1px solid var(--ink);
}
.expression-fields div {
  min-height: 150px;
  padding: 30px 24px;
  border-right: 1px solid var(--rule);
}
.expression-fields div:last-child { border-right: 0; }
.expression-fields dt {
  color: var(--muted);
  font-size: 12px;
  letter-spacing: .08em;
}
.expression-fields dd {
  margin: 18px 0 8px;
  font: 400 34px/1.1 var(--serif);
}
.expression-fields small {
  color: var(--faint);
  font-size: 12px;
}
.expression-top,
.expression-combos,
.expression-members {
  width: 100%;
  max-width: 100%;
}
.expression-top { margin-top: 52px; }
.expression-top h3 {
  margin: 0 0 18px;
  font-size: 22px;
  font-weight: 500;
}
.expression-list {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 14px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.expression-list li {
  padding: 10px 16px;
  background: var(--paper-light);
  border: 1px solid var(--rule);
  border-radius: 4px;
  color: var(--muted);
  font-size: 15px;
}
.expression-list li strong {
  margin-left: 10px;
  color: var(--ink);
  font: 500 16px/1 var(--serif);
}
.expression-list li img.expression-asset {
  width: 28px;
  height: 28px;
  margin-right: 6px;
  vertical-align: -7px;
}
.voice-expression {
  display: inline-block;
  width: 1.28em;
  height: 1.28em;
  margin-right: .14em;
  object-fit: contain;
  vertical-align: -.26em;
}
.expression-list li .expression-name {
  margin-right: 6px;
  color: var(--ink);
  font-size: 15px;
}
.expression-list li .expression-nearby {
  display: block;
  margin-top: 5px;
  color: var(--muted);
  font-size: 12px;
}
.expression-list li .expression-fallback {
  color: var(--muted);
  font-size: 14px;
}
.expression-list li .expression-emoji-fallback {
  font-size: 30px;
  line-height: 1.1;
  vertical-align: -4px;
}
.expression-list li small {
  display: block;
  margin-top: 5px;
  color: var(--faint);
  font-size: 12px;
}
.expression-combos { margin-top: 42px; }
.expression-combos h3 {
  margin: 0 0 18px;
  font-size: 22px;
  font-weight: 500;
}
.expression-combo-list {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 14px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.expression-combo-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  padding: 10px 16px;
  background: var(--paper-light);
  border: 1px solid var(--rule);
  border-radius: 4px;
  color: var(--muted);
  font-size: 15px;
}
.expression-combo-images {
  display: flex;
  align-items: center;
  gap: 8px;
}
.expression-combo-images .expression-asset {
  display: inline-block;
  width: 42px;
  height: 42px;
  flex: 0 0 42px;
  object-fit: contain;
}
.expression-combo-item strong {
  margin-left: 0;
  color: var(--ink);
  font: 500 16px/1 var(--serif);
}
.expression-combo-plus { color: var(--faint); }
.expression-combo-members {
  display: block;
  margin-top: 5px;
  color: var(--muted);
  font-size: 12px;
}
.expression-members {
  height: 460px;
  margin-top: 58px;
  overflow-y: hidden;
  border-top: 1px solid var(--ink);
}
.expression-members:hover { overflow-y: auto; }
.expression-member { padding: 28px 0; border-bottom: 1px solid var(--rule); }
.expression-member header { display: flex; align-items: baseline; gap: 18px; }
.expression-member h3 { margin: 0; font: 500 24px/1.3 var(--sans); }
.expression-summary { margin: 12px 0 0; color: var(--muted); font: 14px/1.8 var(--serif); }
.expression-summary strong {
  color: var(--ink);
  font-weight: 500;
  font-family: var(--serif);
}

.future { display: flex; flex-direction: column; }
.future-list { margin-top: 64px; border-top: 1px solid var(--rule); }
.future-list > div { display: grid; grid-template-columns: 54px 180px 1fr; gap: 24px; align-items: baseline; padding: 28px 0; color: var(--faint); border-bottom: 1px solid var(--rule); }
.future-list span { font: 14px/1 var(--serif); }
.future-list h3 { margin: 0; color: var(--muted); font-size: 20px; font-weight: 500; }
.future-list p { margin: 0; font-size: 13px; }
.end-mark { display: flex; justify-content: space-between; margin-top: auto; padding-top: 80px; color: var(--muted); font-size: 12px; }
.end-mark::before { position: absolute; right: 0; bottom: 112px; left: 0; height: 1px; content: ""; background: linear-gradient(90deg, var(--accent), transparent 76%); }
.end-mark b { font-weight: 400; }


/* === Session 5-section narrative === */
.session-viewer-identity {
  margin: 0 0 30px;
  color: var(--muted);
  font: 15px/1.8 var(--serif);
  letter-spacing: 0.04em;
}

.session-movement {
  margin-top: 36px;
  padding-top: 22px;
  border-top: 1px solid var(--rule);
}

.movement-heading {
  display: flex;
  align-items: center;
  gap: 14px;
  margin: 0 0 16px;
  font: 500 22px/1.3 var(--serif);
  letter-spacing: 0.02em;
}

.movement-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  color: var(--accent);
  font-family: var(--music);
  font-size: 18px;
}

.movement-icon::before {
  content: "♪";
  font-size: 20px;
  line-height: 1;
}

.session-beat-lead {
  margin: 0;
  color: var(--ink);
  font: 17px/1.8 var(--serif);
  letter-spacing: 0.01em;
}

.peak-hour-note {
  margin: 8px 0 0;
  color: var(--muted);
  font: 14px/1.8 var(--serif);
}

#session-movement .session-fields div,
#session-reply .session-fields div,
#session-movement .session-fields div:nth-child(odd),
#session-reply .session-fields div:nth-child(odd),
#session-movement .session-fields div:nth-child(even),
#session-reply .session-fields div:nth-child(even) {
  min-height: auto;
  padding: 18px 20px;
  border-top: 0;
  border-bottom: 0;
  border-right: 1px solid var(--rule);
}

#session-movement .session-fields div:last-child,
#session-reply .session-fields div:last-child {
  border-right: 0;
}

.session-character {
  margin: 16px 0 0;
  padding: 16px 20px;
  color: var(--ink);
  font: 17px/1.7 var(--serif);
  letter-spacing: 0.03em;
  background: var(--paper-light);
  border-left: 3px solid var(--accent-soft);
  border-radius: 2px;
}

/* === Highnote grid === */
.highnote-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1px;
  border: 1px solid var(--rule);
  background: var(--rule);
}

.highnote-card {
  padding: 20px 18px;
  background: var(--paper);
}

.highnote-time {
  display: block;
  margin-top: 8px;
  color: var(--faint);
  font: 12px/1.6 var(--sans);
  letter-spacing: 0.04em;
}

.highnote-badge {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 12px;
  padding: 3px 12px;
  color: var(--accent);
  font: 600 11px/1.6 var(--sans);
  letter-spacing: 0.12em;
  text-transform: uppercase;
  border: 1px solid var(--accent-soft);
  border-radius: 2px;
}

.highnote-note {
  font-family: var(--music);
  font-size: 14px;
  line-height: 1;
}

.highnote-stat {
  display: block;
  color: var(--ink);
  font: 400 20px/1.4 var(--serif);
  letter-spacing: -0.01em;
}

@media (max-width: 720px) {
  .report { width: 100%; margin: 0; }
  .page { min-height: auto; margin: 0; padding: 48px 22px 72px; box-shadow: none; }
  .cover { min-height: 100vh; }
  .toc-row { grid-template-columns: 34px minmax(0, 1fr) 22px; }
  .toc-leader { display: none; }
  .figure-block figcaption { display: block; }
  .figure-block figcaption p { margin-top: 9px; }
  .primary-figure { display: block; }
  .primary-figure strong { display: block; margin-top: 50px; }
  .field-unit { display: block; text-align: left; }
  .archive-fields { grid-template-columns: 1fr; }
  .archive-fields div, .archive-fields div:nth-child(odd), .archive-fields div:nth-child(even) { padding: 24px 0; border-right: 0; border-bottom: 1px solid var(--rule); }
  .archive-fields .wide { grid-column: auto; }
  .session-fields { grid-template-columns: 1fr; }
  .session-fields div, .session-fields div:nth-child(odd), .session-fields div:nth-child(even) { padding: 24px 0; border-right: 0; border-bottom: 1px solid var(--rule); }
  .highnote-grid { grid-template-columns: 1fr; }
  .session-rest-note { margin-top: 40px; }
  .member-list.mode-private { display: block; }
  .member-list.mode-group { display: block; }
  .mode-private .voice-entry, .mode-private .voice-entry + .voice-entry { min-height: auto; padding-right: 0; padding-left: 0; border-left: 0; }
  .voice-descriptor, .voice-words, .voice-context { margin-left: 0; }
  .member-list.mode-group .voice-words { gap: 8px 12px; }
  .member-list.mode-group .voice-words li { font-size: 20px; }
  .member-list.mode-group .voice-words li::after { margin-left: 12px; }
  .expression-fields { grid-template-columns: 1fr; }
  .sticker-members { grid-template-columns: 1fr; gap: 28px; }
  .sticker-member + .sticker-member { border-left: 0; padding-left: 0; border-top: 1px solid var(--rule); padding-top: 24px; }
  .sticker-section-heading { display: block; }
  .sticker-section-heading h3 { margin-bottom: 8px; }
  .sticker-dynamic { flex-direction: column; gap: 24px; }
  .expression-fields div,
  .expression-fields div:last-child {
    min-height: auto;
    padding: 22px 0;
    border-right: 0;
    border-bottom: 1px solid var(--rule);
  }
  .expression-fields div:last-child { border-bottom: 0; }
  .future-list > div { grid-template-columns: 34px 1fr; }
  .future-list p { grid-column: 2; }
  .page-number { right: 22px; }
}

@media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } }

@media print {
  body { background: #fff; }
  .report { width: auto; margin: 0; }
  .page { min-height: 100vh; margin: 0; box-shadow: none; break-after: page; }
  .cover-footer a, .end-mark a { display: none; }
  /* On paper the group list unfolds completely instead of scrolling. */
  .member-list.mode-group { max-height: none; overflow: visible; }
}

"""


ECHO_REPORT_APP_JS = r"""
"use strict";

document.documentElement.classList.add("js-ready");

(function () {
  "use strict";

  var data = window.ECHO_DATA || null;
  var overview = data && data.overview ? data.overview : null;
  var conversation = data && data.conversation ? data.conversation : null;
  var hasData = Boolean(overview && overview.has_data);
  var emptyDescription =
    overview && overview.empty_description ? overview.empty_description : "";

  function setText(id, value) {
    var node = document.getElementById(id);
    if (node) {
      node.textContent = value;
    }
  }

  function setHidden(id, hidden) {
    var node = document.getElementById(id);
    if (node) {
      node.hidden = Boolean(hidden);
    }
  }

  function formatCount(value) {
    return String(Number(value) || 0).replace(
      /\B(?=(\d{3})+(?!\d))/g,
      ","
    );
  }

  function formatPercent(value) {
    return ((Number(value) || 0) * 100).toFixed(1) + "%";
  }

  function formatAverage(value) {
    return (Number(value) || 0).toFixed(1);
  }

  function finiteNumber(value) {
    if (value === null || value === "" || typeof value === "boolean") {
      return null;
    }
    var number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function formatSessionDuration(value) {
    var seconds = finiteNumber(value);
    if (seconds === null || seconds < 0) {
      return "时长未知";
    }
    var totalMinutes = Math.round(seconds / 60);
    if (totalMinutes < 60) {
      return String(totalMinutes) + " 分钟";
    }
    var hours = Math.floor(totalMinutes / 60);
    var minutes = totalMinutes % 60;
    return (
      String(hours) + " 小时" +
      (minutes ? " " + String(minutes) + " 分钟" : "")
    );
  }

  function formatSessionMessages(value) {
    var count = finiteNumber(value);
    if (count === null || count < 0) {
      return "消息数未知";
    }
    return Number.isInteger(count) ? String(count) : count.toFixed(1);
  }

  function formatReplyDuration(value) {
    var seconds = finiteNumber(value);
    if (seconds === null || seconds < 0) {
      return "时长未知";
    }
    if (seconds < 60) {
      return String(Math.round(seconds)) + " 秒";
    }
    return formatSessionDuration(seconds);
  }

  document.querySelectorAll("[data-current-year]").forEach(function (element) {
    element.textContent = String(new Date().getFullYear());
  });

  var title =
    (data && data.title) ||
    (conversation && conversation.name) ||
    "余音 Echo · 聊天记忆报告";
  setText("cover-title", title);
  if (data && data.title) {
    document.title = data.title + " · 余音 Echo";
  }

  var timeSpan =
    conversation && conversation.time_span ? conversation.time_span : "";
  var coverRange = document.getElementById("cover-range");
  if (coverRange) {
    coverRange.textContent = timeSpan ? timeSpan : "本地生成";
    coverRange.hidden = !timeSpan;
  }

  if (overview) {
    setText(
      "overview-message-count",
      hasData ? formatCount(overview.total_message_count) : "—"
    );
    setText("overview-time-span", timeSpan ? timeSpan : "—");
    setText(
      "overview-participants",
      hasData ? formatCount(overview.participant_count) + " 人" : "—"
    );
    setText(
      "overview-active-days",
      hasData && finiteNumber(overview.active_days) > 0
        ? formatCount(overview.active_days) + " 天"
        : "—"
    );
    setText(
      "overview-average-per-day",
      hasData && finiteNumber(overview.average_messages_per_active_day) !== null
        ? formatAverage(overview.average_messages_per_active_day) + " 条"
        : "—"
    );
    if (!hasData && emptyDescription) {
      setText("overview-intro", emptyDescription);
    }
  }

  var sessions = data && data.conversation_sessions;
  var sessionsToc = document.getElementById("session-toc");
  var sessionsChapter = document.getElementById("conversation-sessions");
  var sessionCount = sessions ? finiteNumber(sessions.session_count) : null;
  var hasSessions = Boolean(
    sessions && sessionCount !== null && sessionCount > 0
  );
  if (sessionsChapter) {
    sessionsChapter.hidden = !hasSessions;
  }
  if (sessionsToc) {
    sessionsToc.hidden = !hasSessions;
  }
  if (hasSessions) {
    var conversationKind = conversation && conversation.kind;
    var isPrivate = conversationKind === "private";
    var isGroup = conversationKind === "group";
    setText(
      "session-lead",
      isPrivate
        ? "过去这段时间，你们一共聊起了 " + formatCount(sessionCount) + " 轮"
        : isGroup
          ? "过去这段时间，群里一共聊起了 " + formatCount(sessionCount) + " 轮"
          : "过去这段时间，一共聊起了 " + formatCount(sessionCount) + " 轮"
    );

    // Viewer identity (secondary text, group only)
    var groupInitiators = sessions.group_initiators;
    var viewerIdentityReliable = sessions.viewer_identity_reliable;
    if (isGroup && viewerIdentityReliable && groupInitiators) {
      var selfCount = finiteNumber(groupInitiators.self_count);
      var selfShare = finiteNumber(groupInitiators.self_share);
      if (selfCount !== null && selfShare !== null) {
        setText(
          "session-viewer-identity",
          "你发起了 " + formatCount(selfCount) + " 轮，占 " + formatPercent(selfShare)
        );
        setHidden("session-viewer-identity", false);
      }
    } else {
      setHidden("session-viewer-identity", true);
    }

    // === Private mode: five-section narrative ===
    if (isPrivate) {

      // 总览 / 第一句话
      setText("session-beat-title", "总览 · 第一句话");
      setHidden("session-beat", false);
      var initiators = sessions.private_initiators;
      var selfCount = initiators ? finiteNumber(initiators.self_count) : null;
      var peerCount = initiators ? finiteNumber(initiators.peer_count) : null;
      if (selfCount !== null && peerCount !== null && selfCount + peerCount > 0) {
        setText("session-group-top", "你开启 " + formatCount(selfCount) + " 轮 · TA 开启 " + formatCount(peerCount) + " 轮");
        setHidden("session-group-top", false);
      } else {
        setText("session-group-top", "");
        setHidden("session-group-top", true);
      }
      var selfPeakHour = finiteNumber(sessions.private_self_peak_start_hour);
      if (selfPeakHour !== null) {
        setText("session-self-peak-hour", "你最容易在 " + String(selfPeakHour) + ":00 左右开口");
        setHidden("session-self-peak-hour", false);
      } else {
        setHidden("session-self-peak-hour", true);
      }
      var peerPeakHour = finiteNumber(sessions.private_peer_peak_start_hour);
      if (peerPeakHour !== null) {
        setText("session-peer-peak-hour", "TA 最容易在 " + String(peerPeakHour) + ":00 左右开口");
        setHidden("session-peer-peak-hour", false);
      } else {
        setHidden("session-peer-peak-hour", true);
      }
      setHidden("session-peak-hour", true);

      // 接住第一句话
      var selfToPeer = finiteNumber(sessions.private_reply_median_self_to_peer_seconds);
      var peerToSelf = finiteNumber(sessions.private_reply_median_peer_to_self_seconds);
      var hasReplyData = selfToPeer !== null || peerToSelf !== null;
      setHidden("session-reply", !hasReplyData);
      setText("session-reply-self-to-peer", selfToPeer !== null ? "约 " + formatReplyDuration(selfToPeer) : "暂无足够样本");
      setText("session-reply-peer-to-self", peerToSelf !== null ? "约 " + formatReplyDuration(peerToSelf) : "暂无足够样本");

      // 几段特别的聊天
      setText("session-highnotes-title", "几段特别的聊天");
      renderLoudest("session-loudest-participants", null, function () { return ""; });
      renderLoudest("session-loudest-back-and-forth", sessions.loudest_most_back_and_forth,
        function (s) {
          var selfMessages = finiteNumber(s.self_message_count);
          var peerMessages = finiteNumber(s.peer_message_count);
          var counts = "你 " + (selfMessages === null ? "—" : formatCount(selfMessages)) + " 条 · TA " + (peerMessages === null ? "—" : formatCount(peerMessages)) + " 条";
          return counts + " · " + formatSessionDuration(s.duration_seconds);
        });

    }

    // === Group mode: 5-section narrative ===
    if (isGroup) {
      setHidden("session-reply", true);
      setHidden("session-self-peak-hour", true);
      setHidden("session-peer-peak-hour", true);

      // 谁来起拍
      setText("session-beat-title", "谁来起拍");
      setHidden("session-beat", false);
      if (groupInitiators && groupInitiators.top_member) {
        var topMember = groupInitiators.top_member;
        setText("session-group-top",
          "最常发起聊天：" + topMember.display_name +
          "（" + formatCount(topMember.count) + " 轮，" + formatPercent(topMember.share) + "）"
        );
      } else {
        setText("session-group-top", "");
      }
      var peakHour = finiteNumber(sessions.peak_start_hour);
      if (peakHour !== null) {
        setText("session-peak-hour", "聊天最容易从 " + String(peakHour) + ":00 左右开始");
        setHidden("session-peak-hour", false);
      } else {
        setHidden("session-peak-hour", true);
      }

      // 聊天里的几个高音
      setText("session-highnotes-title", "聊天里的几个高音");
      renderLoudest("session-loudest-participants", sessions.loudest_most_participants,
        function (s) {
          return String(s.participant_count) + " 人参与 · " + formatSessionMessages(s.message_count) + " 条消息";
        });
      renderLoudest("session-loudest-back-and-forth", null, function () { return ""; });

    }
    if (isPrivate || isGroup) {
      setHidden("session-movement", false);
      setText("session-median-duration", "约 " + formatSessionDuration(sessions.median_duration_seconds));
      setText("session-average-messages", "约 " + formatSessionMessages(sessions.average_message_count) + " 条");
      var charText = sessions.session_character;
      if (charText) {
        setText("session-character", charText);
        setHidden("session-character", false);
      } else {
        setHidden("session-character", true);
      }

      setHidden("session-highnotes", false);
      renderLoudest("session-loudest-messages", sessions.loudest_most_messages,
        function (s) {
          return formatSessionMessages(s.message_count) + " 条消息 · " + formatSessionDuration(s.duration_seconds);
        });
      renderLoudest("session-loudest-duration", sessions.loudest_longest_duration,
        function (s) {
          return formatSessionDuration(s.duration_seconds) + " · " + formatSessionMessages(s.message_count) + " 条消息";
        });
      renderLoudest("session-loudest-densest", sessions.loudest_densest,
        function (s) {
          return formatSessionMessages(s.message_count) + " 条消息 · " + formatSessionDuration(s.duration_seconds);
        });
      setHidden("session-rest", false);
      var thresholdSeconds = finiteNumber(sessions.threshold_seconds);
      var thresholdMinutes = thresholdSeconds !== null && thresholdSeconds > 0 ? Math.round(thresholdSeconds / 60) : 30;
      setText("session-threshold-note",
        "超过 " + String(thresholdMinutes) + " 分钟未继续交流，会视作下一轮聊天。"
      );
    }
  }

  function formatTimestamp(ts) {
    if (ts === null || ts === undefined || ts === "") {
      return null;
    }
    var d = new Date(Number(ts) * 1000);
    if (isNaN(d.getTime())) return null;
    var y = String(d.getFullYear()).slice(-2);
    var m = String(d.getMonth() + 1);
    var day = String(d.getDate());
    var hh = String(d.getHours()).padStart(2, "0");
    var mm = String(d.getMinutes()).padStart(2, "0");
    return y + "/" + m + "/" + day + " \u00b7 " + hh + ":" + mm;
  }

  function renderLoudest(containerId, session, formatFn) {
    var container = document.getElementById(containerId);
    if (!container) return;
    if (session && session.message_count > 0) {
      container.hidden = false;
      var textId = containerId + "-text";
      var textNode = document.getElementById(textId);
      if (textNode) {
        textNode.textContent = formatFn(session);
      }
      // Set time anchor
      var timeId = containerId + "-time";
      var timeNode = document.getElementById(timeId);
      if (timeNode) {
        var ts = formatTimestamp(session.start_timestamp);
        if (ts) {
          timeNode.textContent = ts;
          timeNode.hidden = false;
        } else {
          timeNode.hidden = true;
        }
      }
    } else {
      container.hidden = true;
    }
  }

  var hourly = (data && data.activity && data.activity.hourly) || [];
  var busiestBlock = document.getElementById("busiest-hour");
  if (busiestBlock) {
    var peak = null;
    hourly.forEach(function (point) {
      if (!peak || Number(point.value) > Number(peak.value)) {
        peak = point;
      }
    });
    if (hasData && peak && peak.label) {
      busiestBlock.textContent = peak.label;
      busiestBlock.hidden = false;
    } else {
      busiestBlock.hidden = true;
    }
  }

  var hourBars = document.getElementById("hour-bars");
  if (hourBars) {
    hourBars.textContent = "";
    if (hasData && hourly.length) {
      var maxHour = 0;
      hourly.forEach(function (point) {
        maxHour = Math.max(maxHour, Number(point.value) || 0);
      });
      hourly.forEach(function (point) {
        var value = Number(point.value) || 0;
        var bar = document.createElement("i");
        bar.style.setProperty(
          "--v",
          String(maxHour > 0 ? Math.round((value / maxHour) * 100) : 0)
        );
        if (maxHour > 0 && value === maxHour) {
          bar.className = "peak";
        }
        hourBars.appendChild(bar);
      });
    }
  }

  var weekdayTracks = document.getElementById("weekday-tracks");
  var weekday = (data && data.activity && data.activity.weekday) || [];
  if (weekdayTracks) {
    weekdayTracks.textContent = "";
    if (hasData && weekday.length) {
      var maxWeekday = 0;
      weekday.forEach(function (point) {
        maxWeekday = Math.max(maxWeekday, Number(point.value) || 0);
      });
      weekday.forEach(function (point) {
        var value = Number(point.value) || 0;
        var row = document.createElement("div");
        var label = document.createElement("span");
        label.textContent = point.label;
        var track = document.createElement("b");
        var fill = document.createElement("i");
        fill.style.setProperty(
          "--v",
          String(maxWeekday > 0 ? Math.round((value / maxWeekday) * 100) : 0) + "%"
        );
        track.appendChild(fill);
        var count = document.createElement("em");
        count.textContent = formatCount(value);
        row.appendChild(label);
        row.appendChild(track);
        row.appendChild(count);
        weekdayTracks.appendChild(row);
      });
    }
  }

  var languageProfile = data && data.language_profile;
  var languageMode = languageProfile && languageProfile.mode;
  setText(
    "voices-intro",
    languageMode === "group_distinctive"
      ? "在这段聊天里，这些词更像 TA。它们只描述当前时间范围与当前群聊。"
      : languageMode === "private_common"
        ? "你们反复说起的词，像两种声音在这段聊天里留下的回声。"
        : "会话类型明确后，才能选择合适的语言画像。"
  );

  function appendWords(parent, words) {
    var list = document.createElement("ol");
    list.className = "voice-words";
    (words || []).forEach(function (word) {
      var item = document.createElement("li");
      var token = document.createElement("span");
      token.className = "voice-word-token";
      appendInlineWord(token, word);
      item.appendChild(token);
      list.appendChild(item);
    });
    parent.appendChild(list);
  }

  function appendInlineWord(container, word) {
    if (typeof word === "object" && word !== null) {
      var src =
        word.asset_key &&
        window.ECHO_ASSETS &&
        window.ECHO_ASSETS[word.asset_key];
      if (src) {
        var img = document.createElement("img");
        img.className = "voice-expression";
        img.src = src;
        img.alt = "";
        container.appendChild(img);
        return;
      }
      container.appendChild(
        document.createTextNode(word.text || "表情")
      );
      return;
    }
    container.appendChild(document.createTextNode(String(word)));
  }

  var memberList = document.getElementById("member-list");
  if (memberList) {
    memberList.textContent = "";
    memberList.className =
      "member-list" +
      (languageMode === "private_common" ? " mode-private" : " mode-group");
    if (!languageProfile || !languageProfile.available) {
      var unavailable = document.createElement("p");
      unavailable.className = "language-unavailable";
      unavailable.textContent =
        (languageProfile && languageProfile.unavailable_reason) ||
        emptyDescription ||
        "暂无可展示的语言画像。";
      memberList.appendChild(unavailable);
    } else {
      (languageProfile.members || []).forEach(function (member, index) {
        var article = document.createElement("article");
        article.className = "voice-entry";

        var header = document.createElement("header");
        var number = document.createElement("span");
        number.className = "member-index";
        number.textContent =
          index < 9 ? "0" + String(index + 1) : String(index + 1);
        var heading = document.createElement("h3");
        heading.textContent = member.heading || member.display_name || "成员";
        header.appendChild(number);
        header.appendChild(heading);
        article.appendChild(header);

        if (languageMode === "group_distinctive") {
          var descriptor = document.createElement("p");
          descriptor.className = "voice-descriptor";
          descriptor.textContent = "在这段聊天里，这些词更像 TA";
          article.appendChild(descriptor);
        }
        appendWords(article, member.primary_words);

        if (languageMode === "group_distinctive" && member.context_words.length) {
          var context = document.createElement("p");
          context.className = "voice-context";
          context.appendChild(document.createTextNode("常聊："));
          member.context_words.forEach(function (word) {
            appendInlineWord(context, word);
            context.appendChild(document.createTextNode(" "));
          });
          article.appendChild(context);
        }
        if (languageMode === "private_common" && member.expression_habits) {
          var habits = member.expression_habits;
          var habitLine = document.createElement("p");
          habitLine.className = "voice-context";
          habitLine.textContent =
            "平均 " + formatSessionMessages(habits.average_length) + " 字 · " +
            "中位 " + formatSessionMessages(habits.median_length) + " 字 · " +
            "最长 " + formatCount(habits.max_length) + " 字 · " +
            "一次连发 " + formatSessionMessages(habits.average_run_length) + " 条";
          article.appendChild(habitLine);
        }
        memberList.appendChild(article);
      });
    }
  }

  var sharedWordsBlock = document.getElementById("private-shared-words");
  var sideWordsBlock = document.getElementById("private-side-words");
  var sharedWordsList = document.getElementById("private-shared-words-list");
  var sideWordsList = document.getElementById("private-side-words-list");
  if (sharedWordsBlock) sharedWordsBlock.hidden = true;
  if (sideWordsBlock) sideWordsBlock.hidden = true;
  if (sharedWordsList) sharedWordsList.textContent = "";
  if (sideWordsList) sideWordsList.textContent = "";
  if (
    languageMode === "private_common" &&
    languageProfile &&
    languageProfile.available &&
    sharedWordsBlock &&
    sharedWordsList
  ) {
    var sharedWords = languageProfile.shared_words || [];
    if (sharedWords.length) {
      sharedWordsBlock.hidden = false;
      sharedWords.forEach(function (item) {
        var entry = document.createElement("li");
        var selfCount = finiteNumber(item.self_count);
        var peerCount = finiteNumber(item.peer_count);
        appendInlineWord(entry, item.word);
        entry.appendChild(
          document.createTextNode(
            " · 你 " + (selfCount === null ? "—" : formatCount(selfCount)) +
            " 次 · TA " + (peerCount === null ? "—" : formatCount(peerCount)) + " 次"
          )
        );
        sharedWordsList.appendChild(entry);
      });
    }
  }
  if (
    languageMode === "private_common" &&
    languageProfile &&
    languageProfile.available &&
    sideWordsBlock &&
    sideWordsList
  ) {
    var sideWords = languageProfile.side_preference_words || [];
    if (sideWords.length) {
      sideWordsBlock.hidden = false;
      sideWords.forEach(function (item) {
        var entry = document.createElement("li");
        var sideLabel = item.emphasis === "self" ? "你更常说" : "TA 更常说";
        appendInlineWord(entry, item.word);
        entry.appendChild(document.createTextNode(" · " + sideLabel));
        sideWordsList.appendChild(entry);
      });
    }
  }

  function appendExpressionEntry(list, item) {
    var entry = document.createElement("li");
    var assetSrc =
      item.asset_key &&
      window.ECHO_ASSETS &&
      window.ECHO_ASSETS[item.asset_key];
    if (assetSrc) {
      var img = document.createElement("img");
      img.className = "expression-asset";
      img.src = assetSrc;
      img.alt = item.display_text;
      img.title = item.display_text;
      img.loading = "lazy";
      if (img.addEventListener) {
        img.addEventListener("error", function () {
          img.style.display = "none";
        });
      }
      entry.appendChild(img);
    } else {
      var fallback = document.createElement("span");
      fallback.className = "expression-fallback";
      if (item.kind === "unicode") {
        fallback.className += " expression-emoji-fallback";
      }
      fallback.textContent = item.display_text;
      entry.appendChild(fallback);
    }
    var count = document.createElement("strong");
    count.textContent = formatCount(item.count) + " 次";
    entry.appendChild(count);
    if (item.nearby_words && item.nearby_words.length) {
      var nearby = document.createElement("span");
      nearby.className = "expression-nearby";
      nearby.textContent =
        "常和这些词一起：" + item.nearby_words.join(" ");
      entry.appendChild(nearby);
    }
    list.appendChild(entry);
  }

  var stickers = data && data.stickers;
  var hasStickers = Boolean(conversation && stickers && stickers.available && stickers.conversation_kind === conversation.kind &&
    (conversation.kind === "private" || conversation.kind === "group"));
  setHidden("stickers", !hasStickers);
  setHidden("sticker-toc", !hasStickers);
  if (hasStickers) {
    var stickerAssets = stickers.assets || {};
    var stickerGroup = stickers.conversation_kind === "group";
    document.getElementById("stickers").classList.toggle("sticker-group", stickerGroup);
    setText("sticker-total", formatCount(stickers.total_send_count) + " 次");
    setText("sticker-unique", formatCount(stickers.unique_material_count) + " 种不同表情包");
    var noSends = stickers.total_send_count === 0;
    setHidden("sticker-fields", noSends);
    setHidden("sticker-empty", !noSends);
    setText("sticker-empty", "这段记录里没有表情包发送。");
    setHidden("sticker-personal-heading", !stickerGroup);
    setHidden("sticker-rankings", noSends);

    function stickerImage(item) {
      var frame = document.createElement("div");
      frame.className = "sticker-image";
      var fallback = document.createElement("span");
      fallback.className = "sticker-placeholder";
      fallback.textContent = "图片暂不可用";
      frame.appendChild(fallback);
      var asset = stickerAssets[item.asset_key];
      if (asset && (asset.status === "available" || asset.status === "preview") &&
          /^data:image\/(png|jpeg|gif|webp);base64,/.test(asset.data_uri || "")) {
        var image = document.createElement("img");
        image.alt = "表情包";
        image.addEventListener("error", function () {
          image.hidden = true;
          frame.classList.remove("has-image");
        });
        image.src = asset.data_uri;
        frame.classList.add("has-image");
        frame.appendChild(image);
      }
      return frame;
    }

    function stickerRanking(container, items, kind) {
      if (!items.length) {
        var empty = document.createElement("p");
        empty.className = "sticker-member-empty";
        empty.textContent = "暂无记录";
        container.appendChild(empty);
        return;
      }
      var expanded = false;
      var list = document.createElement("ol");
      list.className = "sticker-top-list";
      container.appendChild(list);
      var button = document.createElement("button");
      button.type = "button";
      button.className = "sticker-expand";
      button.setAttribute("aria-expanded", "false");
      button.hidden = items.length <= 3;
      container.appendChild(button);
      function render() {
        container.classList.toggle("is-expanded", expanded);
        list.textContent = "";
        items.slice(0, expanded ? items.length : 3).forEach(function (item, index) {
          var entry = document.createElement("li");
          entry.dataset.assetKey = item.asset_key;
          entry.dataset.count = item.count;
          var rank = document.createElement("span");
          rank.className = "sticker-rank";
          rank.textContent = String(index + 1).padStart(2, "0");
          entry.appendChild(rank);
          entry.appendChild(stickerImage(item));
          var count = document.createElement("strong");
          count.className = "sticker-count";
          count.textContent = formatCount(item.count) + " 次";
          entry.appendChild(count);
          if (kind === "private-shared") {
            var detail = document.createElement("small");
            detail.className = "sticker-detail";
            detail.textContent = "我 " + formatCount(item.side_counts[0]) + " 次 · TA " + formatCount(item.side_counts[1]) + " 次";
            entry.appendChild(detail);
          }
          var asset = stickerAssets[item.asset_key];
          if (asset && asset.status === "preview") {
            var preview = document.createElement("small");
            preview.className = "sticker-preview";
            preview.textContent = "预览";
            entry.appendChild(preview);
          }
          list.appendChild(entry);
        });
        button.textContent = expanded ? "收起至 Top 3" : "展开 Top " + items.length;
        button.setAttribute("aria-expanded", String(expanded));
      }
      button.addEventListener("click", function () { expanded = !expanded; render(); });
      render();
    }

    var stickerMembers = document.getElementById("sticker-members");
    var allStickerMembers = (stickers.members || []).filter(function (member) {
      return !stickerGroup || member.send_count > 0;
    });
    var selectedMembers = new Set(allStickerMembers.length ? [0] : []);
    function renderStickerMembers() {
      stickerMembers.textContent = "";
      allStickerMembers.forEach(function (member, index) {
        if (stickerGroup && !selectedMembers.has(index)) { return; }
        var article = document.createElement("article");
        article.className = "sticker-member";
        var heading = document.createElement("h4");
        heading.textContent = stickerGroup ? member.label : (member.label === "我" ? "我最常用" : member.label + " 最常用");
        article.appendChild(heading);
        if (member.send_count !== null) {
          var usage = document.createElement("p");
          usage.className = "sticker-rate";
          usage.textContent = "共发送 " + formatCount(member.send_count) + " 次";
          if (member.unique_material_count !== null && member.unique_material_count !== undefined) {
            usage.textContent += " · 使用过 " + formatCount(member.unique_material_count) + " 种不同表情包";
          }
          article.appendChild(usage);
          if (member.message_count > 0 && Number.isFinite(member.per_hundred_messages)) {
            var rate = document.createElement("p");
            rate.className = "sticker-rate";
            var intensity = member.per_hundred_messages;
            rate.textContent = "每 100 条有效消息发送" +
              (intensity > 0 && intensity < 0.1 ? "不足 0.1" : "约 " + formatAverage(intensity).replace(/\.0$/, "")) + " 次表情包";
            article.appendChild(rate);
          }
        }
        stickerRanking(article, member.top_materials || [], "personal");
        stickerMembers.appendChild(article);
      });
      setText("sticker-member-summary", "选择成员 · 已选 " + selectedMembers.size + " 人");
    }
    renderStickerMembers();
    setHidden("sticker-member-picker", !stickerGroup || !allStickerMembers.length || noSends);
    var memberSearch = document.getElementById("sticker-member-search");
    var memberOptions = document.getElementById("sticker-member-options");
    function renderMemberOptions() {
      memberOptions.textContent = "";
      var query = memberSearch.value.trim().toLocaleLowerCase();
      allStickerMembers.forEach(function (member, index) {
        if (member.label.toLocaleLowerCase().indexOf(query) < 0) { return; }
        var label = document.createElement("label");
        var checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = selectedMembers.has(index);
        checkbox.addEventListener("change", function () {
          if (checkbox.checked) { selectedMembers.add(index); } else { selectedMembers.delete(index); }
          renderStickerMembers();
        });
        label.appendChild(checkbox);
        var name = document.createElement("span");
        name.textContent = member.label + " · " + formatCount(member.send_count) + " 次";
        label.appendChild(name);
        memberOptions.appendChild(label);
      });
    }
    if (stickerGroup && !noSends) { renderMemberOptions(); }
    memberSearch.addEventListener("input", renderMemberOptions);
    var shared = stickers.shared_materials || [];
    var sharedList = document.getElementById("sticker-shared-list");
    if (sharedList) { sharedList.textContent = ""; }
    if (!stickerGroup && shared.length) { stickerRanking(sharedList, shared, "private-shared"); }
    setHidden("sticker-shared", stickerGroup || !shared.length);
    setHidden("sticker-dynamic", stickerGroup || !shared.length);
    var groupRankings = document.getElementById("sticker-group-rankings");
    groupRankings.textContent = "";
    setHidden("sticker-group-rankings", !stickerGroup || noSends);
    if (stickerGroup) {
      [["全群最常用", stickers.total_top_materials || [], "group-total"],
       ["群里共同最常用", shared, "group-shared"]].forEach(function (definition) {
        var block = document.createElement("div");
        var title = document.createElement("h4");
        title.textContent = definition[0];
        block.appendChild(title);
        stickerRanking(block, definition[1], definition[2]);
        groupRankings.appendChild(block);
      });
    }

  }

  var expressionCulture = data && data.expression_culture;
  var expressionChapter = document.getElementById("expression");
  var expressionToc = document.getElementById("expression-toc");
  var expressionTopList = document.getElementById("expression-top-list");
  var expressionMembers = document.getElementById("expression-members");
  var hasExpressionCulture = Boolean(
    expressionCulture && expressionCulture.available
  );
  if (expressionChapter) {
    expressionChapter.hidden = !hasExpressionCulture;
  }
  if (expressionToc) {
    expressionToc.hidden = !hasExpressionCulture;
  }
  if (hasExpressionCulture) {
    setText("expression-intro", "表达在这段交流里留下的共同语言。");
    setText(
      "expression-message-count",
      formatCount(expressionCulture.expression_message_count) + " 条"
    );
    setText(
      "expression-only-count",
      formatCount(expressionCulture.expression_only_message_count) + " 条"
    );
    setText(
      "expression-unique-count",
      formatCount((expressionCulture.top_expressions || []).length) + " 种"
    );
    if (expressionTopList) {
      expressionTopList.textContent = "";
      (expressionCulture.top_expressions || []).forEach(function (item) {
        appendExpressionEntry(expressionTopList, item);
      });
    }
    var expressionCombos = document.getElementById("expression-combos");
    var expressionComboList = document.getElementById("expression-combo-list");
    var combos = expressionCulture.top_combinations || [];
    var hasCombos = Boolean(
      combos.length
    );
    if (expressionCombos) {
      expressionCombos.hidden = !hasCombos;
    }
    if (expressionComboList) {
      expressionComboList.textContent = "";
      combos.forEach(function (combo) {
        var entry = document.createElement("li");
        entry.className = "expression-combo-item";
        var images = document.createElement("span");
        images.className = "expression-combo-images";
        var labels = combo.labels || [];
        (combo.asset_keys || []).forEach(function (assetKey, index) {
          if (index > 0) {
            var plus = document.createElement("span");
            plus.className = "expression-combo-plus";
            plus.textContent = "+";
            images.appendChild(plus);
          }
          if (assetKey && window.ECHO_ASSETS && window.ECHO_ASSETS[assetKey]) {
            var img = document.createElement("img");
            img.className = "expression-asset";
            img.src = window.ECHO_ASSETS[assetKey];
            img.alt = "";
            img.loading = "lazy";
            images.appendChild(img);
          } else {
            var fallback = document.createElement("span");
            fallback.className = "expression-fallback";
            fallback.textContent = labels[index] || "表情";
            images.appendChild(fallback);
          }
        });
        entry.appendChild(images);
        var count = document.createElement("strong");
        count.textContent = formatCount(combo.count) + " 次";
        entry.appendChild(count);
        if (combo.common_members && combo.common_members.length) {
          var members = document.createElement("span");
          members.className = "expression-combo-members";
          members.textContent =
            "常用者：" +
            combo.common_members
              .map(function (member) {
                return (
                  member.display_name +
                  " " +
                  formatCount(member.count) +
                  " 次 · " +
                  (member.share_percent || 0).toFixed(1) +
                  "%"
                );
              })
              .join("，");
          entry.appendChild(members);
        }
        expressionComboList.appendChild(entry);
      });
    }
    if (expressionMembers) {
      expressionMembers.textContent = "";
      (expressionCulture.members || []).forEach(function (member) {
        var article = document.createElement("article");
        article.className = "expression-member";
        var header = document.createElement("header");
        var name = document.createElement("h3");
        name.textContent = member.display_name;
        header.appendChild(name);
        article.appendChild(header);
        var memberList = document.createElement("ul");
        memberList.className = "expression-list";
        (member.top_expressions || []).forEach(function (item) {
          appendExpressionEntry(memberList, item);
        });
        article.appendChild(memberList);
        expressionMembers.appendChild(article);
      });
    }
  }
})();

"""
