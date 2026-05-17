from flask import Flask, jsonify
import requests
from bs4 import BeautifulSoup
import re
import concurrent.futures

app = Flask(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}

# ── Fetch spot price from a known option page for that index ──────────────────
def fetch_spot(symbol, known_strike, opt_type="CE"):
    url = f"https://munafasutra.com/nse/optionsChart/{symbol}/{opt_type}/{known_strike}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        m = re.search(rf'Spot price of {symbol}:\s*([\d,]+\.?\d*)', r.text)
        if m:
            return float(m.group(1).replace(",", ""))
    except Exception:
        pass
    return None

def get_spot_prices():
    # Use a rough known strike just to get the spot — actual strikes built from spot after
    nifty_spot = fetch_spot("NIFTY",     23500, "CE") or 23650
    bn_spot    = fetch_spot("BANKNIFTY", 55900, "CE") or 53700
    return nifty_spot, bn_spot

# ── Build ATM strikes around spot (step=50 for NIFTY, 100 for BN) ─────────────
def build_strikes(spot, step, count=6):
    atm = round(spot / step) * step
    strikes = []
    for i in range(-count//2, count//2 + 1):
        strikes.append(int(atm + i * step))
    return strikes

# ── Scrape one individual option page ─────────────────────────────────────────
def parse_option_page(symbol, strike, opt_type):
    url = f"https://munafasutra.com/nse/optionsChart/{symbol}/{opt_type}/{strike}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text(" ", strip=True)

        def ex(pattern, default="N/A"):
            m = re.search(pattern, text)
            return m.group(1).strip() if m else default

        price    = ex(r'trading at ₹\s*([\d.]+)')
        avg10    = ex(r'10 minute average:\s*₹\s*([\d.]+)')
        avg30    = ex(r'30 minute average:\s*₹\s*([\d.]+)')
        avgH     = ex(r'Hourly average:\s*₹\s*([\d.]+)')
        day_open = ex(r'Day open:\s*₹\s*([\d.]+)')
        day_rng  = ex(r'Day range:\s*([\d.]+ - [\d.]+)')
        oi_raw   = ex(r'Open Interest:\s*([\d,]+\s*(?:\([^)]+\))?)')
        munafa   = ex(r'Munafa Value:\s*(\d+)')
        spot     = ex(r'Spot price of [^:]+:\s*([\d.]+)')
        lot      = ex(r'Lot size of \S+ is:\s*([\d,]+)')
        munafa_text = ex(r'Munafa Value:\s*\d+\s*[-–]\s*([^.]+\.)')

        # expiry from title tag
        title_tag = soup.find('title')
        expiry = "N/A"
        if title_tag:
            em = re.search(r'(\d{1,2} \w+ \d{4})', title_tag.text)
            expiry = em.group(1) if em else "N/A"

        # skip if no real data
        if price == "N/A" and munafa == "N/A":
            return None

        score = int(munafa) if munafa != "N/A" else 50

        return {
            "symbol":       symbol,
            "strike":       strike,
            "type":         opt_type,
            "expiry":       expiry,
            "price":        price,
            "avg10":        avg10,
            "avg30":        avg30,
            "avgH":         avgH,
            "day_open":     day_open,
            "day_range":    day_rng,
            "oi":           oi_raw,
            "munafa_score": score,
            "munafa_text":  munafa_text if munafa_text != "N/A" else "",
            "spot":         spot,
            "lot_size":     lot,
            "url":          url
        }
    except Exception:
        return None

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NSE Options Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;}
body{background:#0f172a;color:white;font-family:Arial;padding:16px;}

.header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:16px;flex-wrap:wrap;gap:10px;}
.title{font-size:22px;font-weight:bold;color:#38bdf8;}
.sub{color:#64748b;margin-top:3px;font-size:12px;}
.refresh-btn{background:#2563eb;border:none;color:white;padding:9px 16px;border-radius:10px;cursor:pointer;font-size:14px;white-space:nowrap;}

.index-tabs{display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap;}
.type-tabs{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap;}
.tab{padding:7px 16px;border-radius:8px;cursor:pointer;border:1px solid #334155;color:#94a3b8;background:#1e293b;font-size:13px;}
.tab.active{background:#2563eb;color:white;border-color:#2563eb;}

.loader{display:none;margin-bottom:12px;color:#38bdf8;font-size:13px;}
.err{color:#f87171;margin:16px 0;font-size:13px;}

.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:14px;}

.card{background:#111827;border-radius:14px;padding:16px;border:1px solid rgba(255,255,255,0.07);position:relative;overflow:hidden;}
.card::before{content:'';position:absolute;top:0;left:0;width:4px;height:100%;border-radius:4px 0 0 4px;}
.card.buy::before{background:#22c55e;}
.card.sell::before{background:#ef4444;}
.card.watch::before{background:#facc15;}

.option-name{font-size:16px;font-weight:bold;padding-left:8px;margin-bottom:2px;}
.expiry{font-size:11px;color:#475569;padding-left:8px;margin-bottom:10px;}

.top-row{display:flex;align-items:center;justify-content:space-between;padding-left:8px;margin-bottom:12px;}
.signal-badge{padding:3px 10px;border-radius:50px;font-size:11px;font-weight:bold;}
.badge-buy{background:#14532d;color:#4ade80;}
.badge-sell{background:#7f1d1d;color:#f87171;}
.badge-watch{background:#713f12;color:#fde68a;}

.score-block{display:flex;align-items:center;gap:8px;padding:0 8px 12px;}
.score-label{font-size:11px;color:#64748b;white-space:nowrap;}
.score-bar-bg{flex:1;background:#1e293b;border-radius:50px;height:7px;overflow:hidden;}
.score-bar{height:100%;border-radius:50px;}
.score-num{font-size:14px;font-weight:bold;min-width:26px;text-align:right;}
.score-desc{font-size:11px;color:#94a3b8;padding:0 8px 10px;line-height:1.4;font-style:italic;}

.row{display:flex;justify-content:space-between;padding:6px 8px;border-bottom:1px dashed rgba(255,255,255,0.05);font-size:12px;}
.row:last-child{border-bottom:none;}
.lbl{color:#64748b;}
.ltp{color:#38bdf8;font-weight:bold;font-size:14px;}
.up{color:#22c55e;}
.dn{color:#ef4444;}
.oi{color:#a78bfa;}
.neutral{color:#94a3b8;}

.timestamp{text-align:center;color:#334155;font-size:11px;margin-top:16px;}
.spot-bar{background:#1e293b;border-radius:8px;padding:8px 12px;margin-bottom:14px;font-size:12px;color:#94a3b8;display:flex;gap:20px;flex-wrap:wrap;}
.spot-bar span{color:#38bdf8;font-weight:bold;}
</style>
</head>
<body>

<div class="header">
  <div>
    <div class="title">NSE OPTIONS DASHBOARD</div>
    <div class="sub">NIFTY &amp; BANKNIFTY — Munafa Score &amp; Signal</div>
  </div>
  <button onclick="loadData()" class="refresh-btn">⟳ Refresh</button>
</div>

<div id="spotbar" class="spot-bar" style="display:none"></div>

<div class="index-tabs">
  <div class="tab active" onclick="switchIndex('NIFTY',this)">NIFTY</div>
  <div class="tab" onclick="switchIndex('BANKNIFTY',this)">BANKNIFTY</div>
</div>
<div class="type-tabs">
  <div class="tab active" onclick="switchType('CE',this)">CALL (CE)</div>
  <div class="tab" onclick="switchType('PE',this)">PUT (PE)</div>
</div>

<div class="loader" id="loader">⏳ Fetching live options data... this may take 15-20 sec</div>
<div id="err" class="err" style="display:none"></div>
<div class="grid" id="grid"></div>
<div class="timestamp" id="ts"></div>

<script>
let idx = 'NIFTY', typ = 'CE';
let store = {};

function switchIndex(i, el){
  idx = i;
  document.querySelectorAll('.index-tabs .tab').forEach(t=>t.classList.remove('active'));
  el.classList.add('active');
  render();
}
function switchType(t, el){
  typ = t;
  document.querySelectorAll('.type-tabs .tab').forEach(t=>t.classList.remove('active'));
  el.classList.add('active');
  render();
}

function sig(score){
  if(score>=60) return {label:'BUY',  cls:'buy',   badge:'badge-buy'};
  if(score>=40) return {label:'WATCH',cls:'watch', badge:'badge-watch'};
  return             {label:'SELL', cls:'sell',  badge:'badge-sell'};
}
function barColor(score){
  if(score>=60) return '#22c55e';
  if(score>=40) return '#facc15';
  return '#ef4444';
}
function avgCls(price, avg){
  if(avg==='N/A') return 'neutral';
  return parseFloat(price) > parseFloat(avg) ? 'up' : 'dn';
}

function card(item){
  const s = sig(item.munafa_score);
  const c = barColor(item.munafa_score);
  return `<div class="card ${s.cls}">
    <div class="option-name">${item.symbol} ${item.strike} ${item.type}</div>
    <div class="expiry">Expiry: ${item.expiry} &nbsp;|&nbsp; Lot: ${item.lot_size}</div>
    <div class="top-row">
      <span class="ltp">₹${item.price}</span>
      <span class="signal-badge ${s.badge}">${s.label}</span>
    </div>
    <div class="score-block">
      <span class="score-label">Munafa Score</span>
      <div class="score-bar-bg"><div class="score-bar" style="width:${item.munafa_score}%;background:${c}"></div></div>
      <span class="score-num" style="color:${c}">${item.munafa_score}</span>
    </div>
    ${item.munafa_text ? `<div class="score-desc">${item.munafa_text}</div>` : ''}
    <div class="row"><span class="lbl">Day Open</span><span class="neutral">₹${item.day_open}</span></div>
    <div class="row"><span class="lbl">Day Range</span><span class="neutral">${item.day_range}</span></div>
    <div class="row"><span class="lbl">10 Min Avg</span><span class="${avgCls(item.price,item.avg10)}">₹${item.avg10}</span></div>
    <div class="row"><span class="lbl">30 Min Avg</span><span class="${avgCls(item.price,item.avg30)}">₹${item.avg30}</span></div>
    <div class="row"><span class="lbl">Hourly Avg</span><span class="${avgCls(item.price,item.avgH)}">₹${item.avgH}</span></div>
    <div class="row"><span class="lbl">Open Interest</span><span class="oi">${item.oi}</span></div>
    <div class="row"><span class="lbl">Spot Price</span><span class="neutral">₹${item.spot}</span></div>
  </div>`;
}

function render(){
  const key = idx+'_'+typ;
  const data = store[key] || [];
  document.getElementById('grid').innerHTML = data.length
    ? data.map(card).join('')
    : '<div class="err">No data for this selection.</div>';
}

async function loadData(){
  document.getElementById('loader').style.display='block';
  document.getElementById('err').style.display='none';
  document.getElementById('grid').innerHTML='';
  document.getElementById('ts').innerText='';
  document.getElementById('spotbar').style.display='none';
  try{
    const res = await fetch('/api/options');
    const data = await res.json();
    if(data.error){
      document.getElementById('err').innerText = data.error;
      document.getElementById('err').style.display='block';
    } else {
      store = data.cards;
      // spot bar
      const sb = document.getElementById('spotbar');
      sb.innerHTML = `NIFTY Spot: <span>${data.spots.nifty}</span> &nbsp;&nbsp; BANKNIFTY Spot: <span>${data.spots.banknifty}</span>`;
      sb.style.display='flex';
      render();
      document.getElementById('ts').innerText = 'Last updated: ' + new Date().toLocaleTimeString('en-IN');
    }
  } catch(e){
    document.getElementById('err').innerText = 'Failed to load. Please refresh.';
    document.getElementById('err').style.display='block';
  }
  document.getElementById('loader').style.display='none';
}

loadData();
</script>
</body>
</html>"""


@app.route('/')
def home():
    return HTML


@app.route('/api/options')
def options_api():
    try:
        nifty_spot, bn_spot = get_spot_prices()

        nifty_strikes = build_strikes(nifty_spot, 50, 6)
        bn_strikes    = build_strikes(bn_spot, 100, 6)

        tasks = []
        for s in nifty_strikes:
            tasks.append(("NIFTY",     s, "CE"))
            tasks.append(("NIFTY",     s, "PE"))
        for s in bn_strikes:
            tasks.append(("BANKNIFTY", s, "CE"))
            tasks.append(("BANKNIFTY", s, "PE"))

        def fetch(t): return parse_option_page(t[0], t[1], t[2])

        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
            results = list(ex.map(fetch, tasks))

        cards = {"NIFTY_CE":[], "NIFTY_PE":[], "BANKNIFTY_CE":[], "BANKNIFTY_PE":[]}
        for r in results:
            if r:
                key = f"{r['symbol']}_{r['type']}"
                if key in cards:
                    cards[key].append(r)

        # Sort each group by munafa score desc
        for k in cards:
            cards[k].sort(key=lambda x: x["munafa_score"], reverse=True)

        return jsonify({
            "cards": cards,
            "spots": {"nifty": nifty_spot, "banknifty": bn_spot}
        })

    except Exception as e:
        return jsonify({"error": str(e)})


if __name__ == '__main__':
    app.run(debug=False)
