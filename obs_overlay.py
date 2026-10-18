"""
OBS 채팅 화면 (내 컴퓨터 안에서만 열리는 작은 웹 서버)
=====================================================

OBS 에서 쓰는 방법
  - 방송 화면에 채팅 띄우기:  소스 [+] → 브라우저 → http://127.0.0.1:8765/chat   (보기 전용)
  - OBS 창 안에 붙이기:       [독] → 사용자 지정 브라우저 독 → http://127.0.0.1:8765/dock
                             (방송 상태 + 채팅 + 제목 입력칸 + 채팅 입력칸. 스트리머만 봐요)

주소 뒤에 옵션을 붙일 수 있어요. (예: http://127.0.0.1:8765/chat?theme=light&size=24&lines=20)
  theme=dark|light   글자색 (기본 dark = 흰 글자 + 그림자, 투명 배경에 어울려요)
  bg=transparent|solid   배경 (기본 transparent)
  size=20            글자 크기(px, 12~60)
  lines=30           한 번에 보이는 줄 수 (5~100)
  time=0|1           시간 표시 (기본 0)
  donation=0|1       후원 · 구독 카드 표시 (기본 1)
  alert=0            영상 후원 알림 화면을 숨겨요 (기본: [보기] → OBS 영상 후원 알림 주소 설정 에 주소를 넣었으면 위쪽에 같이 나와요)
  altheight=55       영상 후원 알림 화면이 차지할 높이(%, 20~80, 기본 55). 나머지 아래쪽이 채팅이에요
  input=1            OBS 독용 도구 표시: 맨 위 방송 상태(방송 중 · 시청자 · 카테고리 · 제목 · 게임) +
                     맨 아래 제목 입력칸 + 채팅 입력칸. (방송 화면용 브라우저 소스에는 붙이지 마세요)
  status=0 / title=0 input=1 일 때 상태줄 / 제목 입력칸을 숨겨요 (채팅 입력칸만 쓰고 싶을 때)
  backlog=0|1        열 때 지난 채팅도 보여줄지 (기본 0. input=1 독에서는 기본 1)
  hint=1             '채팅 기다리는 중' / '연결 안 됨' 안내 글을 보여줘요 (input=1 독에서는 기본으로 보여요)

영상 후원 (같은 화면에 같이 보기)
  치지직 스튜디오의 '알림 주소'(방송용으로 OBS 브라우저 소스에 넣는 그 주소)를 프로그램에 한 번 넣어 두면,
  이 채팅 화면 위쪽에 그 알림 화면(영상 후원 재생 포함)이 같이 나와요. OBS 소스 하나로 채팅 + 영상 후원이 끝나요.
  - 프로그램이 영상 주소를 받는 게 아니라, 치지직이 주는 알림 화면을 그대로 보여주는 거예요.
  - 알림 주소에는 내 채널 비밀 값이 들어 있어요. 남에게 보여주지 마세요. (init.json 에 저장돼요)
  - 네이버(*.naver.com) 의 https 주소만 허용해요.

안전하게
  - 127.0.0.1(내 컴퓨터)에서만 열려요. 같은 와이파이의 다른 기기에서는 못 봐요.
  - 채팅 · 후원 내용만 내보내요. 키 · 토큰 · 설정은 이 서버가 알지도 못해요.
  - 화면은 글자를 textContent 로만 그려서, 채팅에 이상한 코드가 들어 있어도 실행되지 않아요.
  - 올바른 Host(127.0.0.1 / localhost) 로 온 요청만 받아요. (웹사이트가 몰래 접속하는 걸 막아요)
  - 채팅 보내기(/send) · 제목 바꾸기(/title)는 켤 때마다 새로 만드는 비밀 표(토큰) + JSON + 같은 주소에서 온
    요청일 때만 받아요. (다른 웹사이트가 내 이름으로 채팅을 보내거나 제목을 바꾸지 못하게 막아요.
    채팅은 100자 · 1.5초에 한 번, 제목은 100자 · 3초에 한 번까지)
  - 방송 상태(/status)는 방송 중 여부 · 시청자 수 · 제목 · 카테고리 · 현재 게임만 내보내요. (키 · 토큰 없음)
"""

import json
import secrets
import threading
import time
import urllib.parse
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Deque, Dict, List, Optional, Tuple

N_DEFAULT_PORT = 8765
N_KEEP_EVENTS = 200
STR_HOST = "127.0.0.1"
N_MAX_POLL_EVENTS = 100
TUPLE_ALERT_SUFFIXES = ("naver.com",)   # 영상 후원 알림 주소로 허용하는 도메인 (그 아래 주소 포함)
N_MAX_ALERT_URL = 800
N_MAX_TITLE_CHARS = 100
F_TITLE_INTERVAL_SEC = 3.0
N_MAX_SEND_CHARS = 100          # 치지직 채팅 한 번에 보낼 수 있는 길이
N_MAX_BODY_BYTES = 2048
F_SEND_INTERVAL_SEC = 1.5

STR_CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
           "img-src https://*.pstatic.net https://*.naver.net https://*.naver.com; connect-src 'self'")

def IsAllowedAlertUrl(strUrl: str) -> bool:
    """영상 후원 알림 주소로 써도 되는지: https + 네이버 도메인 + 아이디/비밀번호(user@) 없음 + 공백 · 따옴표 없음."""
    if not isinstance(strUrl, str) or not strUrl or len(strUrl) > N_MAX_ALERT_URL:
        return False
    if any(ch.isspace() or ch in "\"'<>\\`" for ch in strUrl) or not strUrl.isascii():
        return False
    try:
        objParsed = urllib.parse.urlparse(strUrl)
        strHost = (objParsed.hostname or "").lower().rstrip(".")
        objParsed.port  # 포트 숫자가 이상하면 여기서 에러
    except ValueError:
        return False
    if objParsed.scheme != "https" or objParsed.username is not None or objParsed.password is not None:
        return False
    return any(strHost == strSuffix or strHost.endswith("." + strSuffix) for strSuffix in TUPLE_ALERT_SUFFIXES)


STR_PAGE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>OBS chat</title>
<style>
html,body{margin:0;padding:0;background:transparent;overflow:hidden;font-family:"Malgun Gothic","Apple SD Gothic Neo",sans-serif}
body.solid{background:#101114}
#log{position:fixed;left:0;right:0;bottom:0;padding:6px 10px}
.row{display:flex;margin:0 0 5px 0;border-radius:6px;overflow:hidden;animation:in .25s ease-out;word-break:break-word}
.bar{flex:0 0 4px}
.body{padding:4px 9px;line-height:1.35}
.nick{font-weight:700;margin-right:6px}
.time{opacity:.65;font-size:.75em;margin-right:6px}
.badge{font-size:.7em;color:#fff;padding:1px 5px;border-radius:4px;margin-right:6px;vertical-align:middle}
#tools{position:fixed;left:0;right:0;bottom:0;display:none;flex-direction:column;gap:6px;padding:6px 10px;background:rgba(20,20,24,.94)}
#tools form{display:flex;gap:6px}
#tools input{flex:1;min-width:0;font-size:15px;padding:6px 8px;border-radius:6px;border:1px solid #555;background:#1e1f24;color:#fff}
#tools button{font-size:14px;padding:6px 12px;border-radius:6px;border:0;color:#fff;cursor:pointer;white-space:nowrap}
#go{background:#2f9e44}#tgo{background:#1971c2}
#tools button:disabled{opacity:.5}
#stat{position:fixed;left:0;right:0;top:0;display:none;padding:6px 10px;background:rgba(20,20,24,.94);color:#e9ecef;font-size:14px;line-height:1.5}
#stat .chip{display:inline-block;padding:1px 9px;border-radius:10px;background:#495057;color:#fff;margin-right:6px;font-size:13px}
#stat .live{background:#e03131}#stat .t{font-weight:700;display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#stat .sub{color:#adb5bd;font-size:12px}
#hint{white-space:pre-line;position:fixed;left:12px;right:12px;top:42%;text-align:center;font-size:14px;color:#adb5bd;text-shadow:0 1px 2px #000;display:none}
#hint.err{color:#ffa8a8}
#msg{position:fixed;left:12px;right:12px;bottom:90px;font-size:13px;color:#ffa8a8;text-shadow:0 1px 2px #000;display:none}
.dark .row{background:rgba(0,0,0,.35)}
.dark .txt{color:#fff;text-shadow:0 1px 3px rgba(0,0,0,.9),0 0 2px rgba(0,0,0,.9)}
.light .row{background:rgba(255,255,255,.80)}
.light .txt{color:#1f2937}
.sys{justify-content:center;opacity:.7;font-size:.75em;background:transparent!important;color:#9ca3af}
.don{background:#fff3bf!important;color:#1f2937}
.don .bar{flex-basis:6px;background:#f08c00}
.don .kind{font-weight:700;color:#d9480f;font-size:1.1em;margin-right:6px}
.don .nick{color:#1f2937!important}
img.em{height:1.5em;vertical-align:middle;margin:0 1px}
@keyframes in{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
</style></head>
<body><div id="log"></div>
<div id="alertbox"></div>
<div id="stat"><span id="chips"></span><span class="t" id="ttext"></span><span class="sub" id="sub"></span></div>
<div id="hint"></div>
<div id="msg"></div>
<div id="tools">
<form id="tform" autocomplete="off"><input id="ttl" maxlength="100" placeholder="방송 제목 (바꾸려면 입력 후 Enter)"><button id="tgo" type="submit">제목 변경</button></form>
<form id="bar" autocomplete="off"><input id="txt" maxlength="100" placeholder="채팅 입력 후 Enter (최대 100자)"><button id="go" type="submit">보내기</button></form>
</div>
<script>
(function(){
var q=new URLSearchParams(location.search);
if(location.pathname==='/dock'&&!q.has('input'))q.set('input','1');  // /dock 주소는 input=1 을 따로 안 붙여도 돼요
function num(k,d,lo,hi){var v=parseInt(q.get(k),10);if(isNaN(v))v=d;return Math.max(lo,Math.min(hi,v));}
var size=num('size',20,12,60),maxLines=num('lines',30,5,100);
var showTime=q.get('time')==='1',showDon=q.get('donation')!=='0',backlog=q.get('backlog')==='1'||(q.get('input')==='1'&&q.get('backlog')!=='0');
var theme=q.get('theme')==='light'?'light':'dark';
var log=document.getElementById('log');
log.className=theme;log.style.fontSize=size+'px';
if(q.get('bg')==='solid')document.body.className='solid';
function el(tag,cls,text){var e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;}
function fill(box,parts){
  (parts||[]).forEach(function(p){
    if(p[0]==='e'){var i=el('img','em');i.alt=p[2]||'';i.src=p[1];box.appendChild(i);}
    else box.appendChild(document.createTextNode(p[1]));
  });
}
function add(ev){
  var row=el('div','row'),bar=el('div','bar'),body=el('div','body');
  if(ev.type==='system'){row.className='row sys';body.textContent='— '+ev.text+' —';row.appendChild(body);}
  else if(ev.type==='donation'){
    if(!showDon)return;
    row.className='row don';bar.style.background='';
    body.appendChild(el('span','kind',ev.kind+(ev.amount?' '+ev.amount:'')));
    body.appendChild(el('span','nick',ev.nick));
    if(ev.parts&&ev.parts.length){body.appendChild(el('br'));fill(body,ev.parts);}
    row.appendChild(bar);row.appendChild(body);
  }else{
    bar.style.background=ev.color||'#888';
    if(showTime&&ev.time)body.appendChild(el('span','time txt',ev.time));
    if(ev.type==='youtube'){var y=el('span','badge','YT');y.style.background='#ff0000';body.appendChild(y);}
    if(ev.role){var b=el('span','badge',ev.role);b.style.background=ev.roleColor||'#495057';body.appendChild(b);}
    var n=el('span','nick',ev.nick);n.style.color=ev.color||'#fff';body.appendChild(n);
    body.appendChild(el('br'));
    var t=el('span','txt');fill(t,ev.parts);body.appendChild(t);
    row.appendChild(bar);row.appendChild(body);
  }
  log.appendChild(row);
  while(log.children.length>maxLines)log.removeChild(log.firstChild);
}
var ALERT=@@ALERT@@;
if(ALERT&&q.get('alert')!=='0'&&(q.get('input')!=='1'||q.get('alert')==='1')){
  var altH=num('altheight',55,20,80),f=document.createElement('iframe');
  f.src=ALERT;f.setAttribute('sandbox','allow-scripts allow-same-origin');f.referrerPolicy='no-referrer';f.allow='autoplay';
  f.style.cssText='position:fixed;left:0;top:0;width:100%;height:'+altH+'%;border:0;background:transparent;pointer-events:none';
  document.getElementById('alertbox').appendChild(f);log.style.maxHeight=(100-altH)+'%';log.style.overflow='hidden';
}
var TOKEN="@@TOKEN@@";
var dock=q.get('input')==='1';
if(dock){
  var tools=document.getElementById('tools'),stat=document.getElementById('stat'),msg=document.getElementById('msg');
  var showStat=q.get('status')!=='0',showTitle=q.get('title')!=='0';
  tools.style.display='flex';
  if(!showTitle)document.getElementById('tform').style.display='none';
  if(showStat)stat.style.display='block';
  function layout(){
    log.style.bottom=(tools.offsetHeight+4)+'px';msg.style.bottom=(tools.offsetHeight+8)+'px';
    log.style.top=showStat?(stat.offsetHeight+4)+'px':'0px';log.style.overflow='hidden';
  }
  layout();window.addEventListener('resize',layout);
  function note(t){msg.textContent=t;msg.style.display=t?'block':'none';if(t)setTimeout(function(){msg.style.display='none';},4000);}
  function post(path,text,btn,input,okFn){
    if(!text||btn.disabled)return;btn.disabled=true;
    fetch(path,{method:'POST',cache:'no-store',headers:{'Content-Type':'application/json','X-Overlay-Token':TOKEN},body:JSON.stringify({text:text})})
      .then(function(r){return r.json().then(function(d){return [r.ok,d];});})
      .then(function(x){if(x[0]){note('');if(okFn)okFn();}else note(x[1].error||'보내지 못했어요');})
      .catch(function(){note('프로그램에 연결할 수 없어요');})
      .then(function(){btn.disabled=false;input.focus();});
  }
  var txt=document.getElementById('txt'),go=document.getElementById('go'),ttl=document.getElementById('ttl'),tgo=document.getElementById('tgo');
  document.getElementById('bar').addEventListener('submit',function(e){
    e.preventDefault();post('/send',txt.value.trim(),go,txt,function(){txt.value='';});});
  document.getElementById('tform').addEventListener('submit',function(e){
    e.preventDefault();post('/title',ttl.value.trim(),tgo,ttl,function(){ttl.blur();note('');});});
  var firstStat=true;
  function chip(text,cls){var c=el('span','chip'+(cls?' '+cls:''),text);return c;}
  function showStatus(d){
    var chips=document.getElementById('chips');chips.textContent='';
    if(!d||d.live===undefined){document.getElementById('ttext').textContent='방송 상태를 아직 못 받았어요 (프로그램에서 [새로고침])';layout();return;}
    chips.appendChild(chip(d.live?'● 방송 중':'방송 꺼짐',d.live?'live':''));
    if(d.live)chips.appendChild(chip('시청자 '+Number(d.viewers||0).toLocaleString()+'명'));
    if(d.category)chips.appendChild(chip(d.category));
    document.getElementById('ttext').textContent=d.title||'(제목 없음)';
    var sub=[];if(d.game)sub.push('게임: '+d.game);sub.push(d.loggedIn?'치지직 로그인됨':'치지직 로그인 필요');if(d.at)sub.push('갱신 '+d.at);
    document.getElementById('sub').textContent=sub.join('  ·  ');
    if(firstStat&&showTitle&&d.title&&!ttl.value){ttl.value=d.title;}
    firstStat=false;layout();
  }
  function pollStatus(){jf('/status').then(function(r){return r.json();}).then(showStatus).catch(function(){});}
  pollStatus();setInterval(pollStatus,3000);
}
var last=backlog?0:-1,busy=false;
function jf(url){var c=new AbortController();setTimeout(function(){c.abort();},4000);return fetch(url,{cache:'no-store',signal:c.signal});}
var hint=document.getElementById('hint'),showHint=q.get('input')==='1'||q.get('hint')==='1';
function setHint(t,err){if(!showHint)return;hint.textContent=t;hint.className=err?'err':'';hint.style.display=t?'block':'none';}
function poll(){
  if(busy)return;busy=true;
  jf('/events?after='+last).then(function(r){if(!r.ok)throw new Error('http');return r.json();}).then(function(d){
    (d.events||[]).forEach(add);last=d.last;
    setHint(log.children.length?'':'채팅을 기다리는 중… (연결됨)',false);
  }).catch(function(){setHint('프로그램에 연결할 수 없어요.\n방송 도우미 → [보기] → OBS 채팅 화면 켜기 가 체크돼 있는지, 주소의 포트 번호가 맞는지 확인해 주세요.',true);}).then(function(){busy=false;});
}
setInterval(poll,600);poll();
})();
</script></body></html>
"""


class _Handler(BaseHTTPRequestHandler):
    server_version = "BangsongOverlay"
    protocol_version = "HTTP/1.0"

    def log_message(self, strFormat, *args):  # 콘솔에 찍지 않아요.
        pass

    def _Send(self, nCode: int, baBody: bytes, strType: str, strFrameSrc: str = "") -> None:
        self.send_response(nCode)
        self.send_header("Content-Type", strType)
        self.send_header("Content-Length", str(len(baBody)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", STR_CSP + (f"; frame-src https://{strFrameSrc}" if strFrameSrc else ""))
        self.end_headers()
        self.wfile.write(baBody)

    def do_GET(self):  # noqa: N802 (표준 이름)
        objOverlay: "OverlayServer" = self.server.objOverlay
        # 올바른 Host 로 온 요청만 (다른 웹사이트가 내 주소로 몰래 접속하는 걸 막아요)
        if not objOverlay.IsAllowedHost(self.headers.get("Host", "")):
            self._Send(403, b"forbidden", "text/plain; charset=utf-8")
            return
        objUrl = urllib.parse.urlparse(self.path)
        if objUrl.path in ("/", "/chat", "/dock"):
            strAlert = objOverlay.strAlertUrl if IsAllowedAlertUrl(objOverlay.strAlertUrl) else ""
            strPage = (STR_PAGE.replace("@@TOKEN@@", objOverlay.strToken)
                       .replace("@@ALERT@@", json.dumps(strAlert).replace("</", "<\\/")))
            self._Send(200, strPage.encode("utf-8"), "text/html; charset=utf-8",
                       strFrameSrc=urllib.parse.urlparse(strAlert).netloc if strAlert else "")
        elif objUrl.path == "/status":
            self._SendJson(200, objOverlay.GetStatus())
        elif objUrl.path == "/events":
            try:
                nAfter = int(urllib.parse.parse_qs(objUrl.query).get("after", ["0"])[0])
            except ValueError:
                nAfter = 0
            baBody = json.dumps(objOverlay.EventsAfter(nAfter), ensure_ascii=False).encode("utf-8")
            self._Send(200, baBody, "application/json; charset=utf-8")
        else:
            self._Send(404, b"not found", "text/plain; charset=utf-8")

    def _SendJson(self, nCode: int, dictBody: dict) -> None:
        self._Send(nCode, json.dumps(dictBody, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_POST(self):  # noqa: N802 — 채팅 보내기(/send) · 제목 바꾸기(/title)만 받아요.
        objOverlay: "OverlayServer" = self.server.objOverlay
        strPath = urllib.parse.urlparse(self.path).path
        if strPath not in ("/send", "/title"):
            self._Send(405, b"method not allowed", "text/plain; charset=utf-8")
            return
        if not objOverlay.IsAllowedHost(self.headers.get("Host", "")):
            self._Send(403, b"forbidden", "text/plain; charset=utf-8")
            return
        # 다른 웹사이트가 만든 요청 막기: 같은 주소에서 온 것 + JSON + 비밀 표(토큰)가 모두 맞아야 해요.
        strOrigin = (self.headers.get("Origin") or "").lower()
        if strOrigin and strOrigin not in (f"http://{STR_HOST}:{objOverlay.nPort}", f"http://localhost:{objOverlay.nPort}"):
            self._SendJson(403, {"error": "허용되지 않은 요청이에요"})
            return
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            self._SendJson(415, {"error": "JSON 만 받아요"})
            return
        if not secrets.compare_digest(self.headers.get("X-Overlay-Token") or "", objOverlay.strToken):
            self._SendJson(403, {"error": "허용되지 않은 요청이에요"})
            return
        try:
            nLength = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            nLength = -1
        if not (0 < nLength <= N_MAX_BODY_BYTES):
            self._SendJson(400, {"error": "요청이 너무 크거나 비어 있어요"})
            return
        try:
            strText = json.loads(self.rfile.read(nLength).decode("utf-8")).get("text", "")
        except (ValueError, UnicodeDecodeError, AttributeError):
            self._SendJson(400, {"error": "요청 모양이 맞지 않아요"})
            return
        bOk, strMessage = objOverlay.RequestTitle(strText) if strPath == "/title" else objOverlay.RequestSend(strText)
        self._SendJson(200 if bOk else 400, {"ok": True} if bOk else {"error": strMessage})


class _Server(ThreadingHTTPServer):
    allow_reuse_address = False  # 윈도우에서는 켜 두면 이미 쓰는 포트에도 겹쳐 열려서, 끄고 열어요.
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass  # OBS 가 창을 닫거나 새로고침해서 연결이 끊기는 건 흔한 일이라 조용히 넘어가요.


class OverlayServer:
    def __init__(self):
        self.objLock = threading.Lock()
        self.dequeEvents: Deque[dict] = deque(maxlen=N_KEEP_EVENTS)
        self.nNextId = 1
        self.objHttpd: Optional[_Server] = None
        self.objThread: Optional[threading.Thread] = None
        self.nPort = 0
        self.strToken = secrets.token_urlsafe(16)   # 켤 때마다 새로 만들어요. (채팅 보내기 허가증)
        self.strAlertUrl = ""   # 치지직 스튜디오의 '알림 주소' (영상 후원 알림 화면). 비어 있으면 안 보여줘요.
        self.fnSend: Optional[Callable[[str], None]] = None  # 채팅 보내기를 처리하는 곳 (메인 창이 연결)
        self.fLastSendAt = 0.0
        self.fnSetTitle: Optional[Callable[[str], None]] = None  # 방송 제목 바꾸기를 처리하는 곳 (메인 창이 연결)
        self.fLastTitleAt = 0.0
        self.dictStatus: Dict = {}   # 방송 상태 (메인 창이 새로고침할 때마다 갱신)

    @property
    def bIsRunning(self) -> bool:
        return self.objHttpd is not None

    def Url(self) -> str:
        """방송 화면용(OBS 브라우저 소스) 주소. 보기 전용이에요."""
        return f"http://{STR_HOST}:{self.nPort}/chat" if self.bIsRunning else ""

    def DockUrl(self) -> str:
        """OBS 독용 주소. 방송 상태 · 제목 입력칸 · 채팅 입력칸이 같이 나와요. (/chat?input=1 과 같아요)"""
        return f"http://{STR_HOST}:{self.nPort}/dock" if self.bIsRunning else ""

    def IsAllowedHost(self, strHostHeader: str) -> bool:
        return (strHostHeader or "").lower() in (f"{STR_HOST}:{self.nPort}", f"localhost:{self.nPort}")

    def Start(self, nPort: int = N_DEFAULT_PORT) -> Tuple[bool, str]:
        """켜요. 이미 켜져 있으면 그대로. 성공 여부와 메시지를 돌려줘요."""
        if self.bIsRunning:
            return True, self.Url()
        if not (1024 <= int(nPort) <= 65535):
            return False, f"포트 번호가 올바르지 않아요: {nPort} (1024~65535)"
        try:
            objHttpd = _Server((STR_HOST, int(nPort)), _Handler)
        except OSError as objError:
            return False, f"포트 {nPort} 를 열 수 없어요 (이미 다른 프로그램이 쓰는 중일 수 있어요): {objError}"
        objHttpd.objOverlay = self
        self.strToken = secrets.token_urlsafe(16)
        self.objHttpd = objHttpd
        self.nPort = int(nPort)
        self.objThread = threading.Thread(target=objHttpd.serve_forever, name="obs-overlay", daemon=True)
        self.objThread.start()
        return True, self.Url()

    def Stop(self) -> None:
        objHttpd, self.objHttpd = self.objHttpd, None
        if objHttpd is not None:
            objHttpd.shutdown()
            objHttpd.server_close()
        self.objThread = None

    def RequestSend(self, strText: str) -> Tuple[bool, str]:
        """OBS 독 입력칸에서 온 채팅. 길이 · 속도를 확인하고 연결된 곳(fnSend)으로 넘겨요."""
        if not isinstance(strText, str):
            return False, "글자만 보낼 수 있어요"
        strText = "".join(ch for ch in strText if ch.isprintable()).strip()
        if not strText:
            return False, "보낼 글자가 없어요"
        if len(strText) > N_MAX_SEND_CHARS:
            return False, f"{N_MAX_SEND_CHARS}자까지만 보낼 수 있어요"
        if self.fnSend is None:
            return False, "채팅 보내기가 준비되지 않았어요"
        with self.objLock:
            fNow = time.monotonic()
            if fNow - self.fLastSendAt < F_SEND_INTERVAL_SEC:
                return False, "너무 빨리 보내고 있어요. 잠깐 뒤에 다시 보내 주세요"
            self.fLastSendAt = fNow
        self.fnSend(strText)
        return True, ""

    def RequestTitle(self, strText: str) -> Tuple[bool, str]:
        """OBS 독의 제목 입력칸에서 온 요청. 길이 · 속도를 확인하고 연결된 곳(fnSetTitle)으로 넘겨요."""
        if not isinstance(strText, str):
            return False, "글자만 보낼 수 있어요"
        strText = "".join(ch for ch in strText if ch.isprintable()).strip()
        if not strText:
            return False, "제목이 비어 있어요"
        if len(strText) > N_MAX_TITLE_CHARS:
            return False, f"제목은 {N_MAX_TITLE_CHARS}자까지만 쓸 수 있어요"
        if self.fnSetTitle is None:
            return False, "제목 바꾸기가 준비되지 않았어요"
        with self.objLock:
            fNow = time.monotonic()
            if fNow - self.fLastTitleAt < F_TITLE_INTERVAL_SEC:
                return False, "너무 빨리 바꾸고 있어요. 잠깐 뒤에 다시 해 주세요"
            self.fLastTitleAt = fNow
        self.fnSetTitle(strText)
        return True, ""

    def SetStatus(self, dictStatus: dict) -> None:
        """방송 상태를 새로 알려요. (live · viewers · title · category · channel · game · loggedIn · at)"""
        with self.objLock:
            self.dictStatus = dict(dictStatus)

    def GetStatus(self) -> Dict:
        with self.objLock:
            return dict(self.dictStatus)

    def Publish(self, dictEvent: dict) -> None:
        """새 채팅 · 후원을 OBS 화면으로 보낼 목록에 넣어요. (꺼져 있으면 아무것도 안 해요)"""
        if not self.bIsRunning:
            return
        with self.objLock:
            dictEvent = dict(dictEvent, id=self.nNextId)
            self.nNextId += 1
            self.dequeEvents.append(dictEvent)

    def EventsAfter(self, nAfter: int) -> Dict:
        """nAfter 보다 새 이벤트들. nAfter 가 -1 이면 지난 것은 건너뛰고 지금 번호만 알려줘요."""
        with self.objLock:
            nLast = self.nNextId - 1
            if nAfter < 0:
                return {"events": [], "last": nLast}
            if nAfter > nLast:  # 프로그램을 다시 켜서 번호가 처음부터 시작된 경우
                nAfter = 0
            listEvents: List[dict] = [dictItem for dictItem in self.dequeEvents if dictItem["id"] > nAfter]
        return {"events": listEvents[-N_MAX_POLL_EVENTS:], "last": nLast}
