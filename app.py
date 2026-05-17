from flask import Flask, jsonify
import requests
from bs4 import BeautifulSoup
import re
import concurrent.futures

app = Flask(__name__)

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NSE Options Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;}
body{background:#0f172a;color:white;font-family:Arial;padding:20px;}

.header{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;flex-wrap:wrap;gap:10px;}
.title{font-size:26px;font-weight:bold;color:#38bdf8;}
.sub{color:#94a3b8;margin-top:4px;font-size:13px;}
.refresh-btn{background:#2563eb;border:none;color:white;padding:10px 18px;border-radius:10px;cursor:pointer;font-size:15px;}

.tabs{display:flex;gap:10px;margin-bottom:20px;flex-wrap:wrap;}
.tab{padding:8px 20px;border-radius:8px;cursor:pointer;border:1px solid #334155;color:#94a3b8;background:#1e293b;font-size:14px;}
.tab.active{background:#2563eb;color:white;border-color:#2563eb;}

.loader{display:none;margin-bottom:15px;color:#38bdf8;font-size:14px;}
.error{color:#f87171;margin:20px 0;font-size:14px;}

.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px;}

.card{background:#111827;border-radius:16px;padding:18px;border:1px solid rgba(255,255,255,0.07);position:relative;overflow:hidden;}
.card::before{content:'';position:absolute;top:0;left:0;width:4px;height:100%;border-radius:4px 0 0 4px;}
.card.buy::before{background:#22c55e;}
.card.sell::before{background:#ef4444;}
.card.neutral::before{background:#94a3b8;}

.option-name{font-size:17px;font-weight:bold;margin-bottom:4px;padding-left:8px;}
.expiry{font-size:11px;color:#64748b;margin-bottom:12px;padding-left:8px;}

.signal-badge{display:inline-block;padding:4px 12px;border-radius:50px;font-size:12px;font-weight:bold;margin-bottom:14px;margin-left:8px;}
.badge-buy{background:#14532d;color:#4ade80;}
.badge-sell{background:#7f1d1d;color:#f87171;}
.badge-neutral{background:#1e293b;color:#94a3b8;}

.munafa-row{display:flex;align-items:center;gap:10px;margin-bottom:14px;padding-left:8px;}
.munafa-label{font-size:12px;color:#94a3b8;}
.munafa-bar-bg{flex:1;background:#1e293b;border-radius:50px;height:8px;overflow:hidden;}
.munafa-bar{height:100%;border-radius:50px;transition:width 0.5s;}
.munafa-score{font-size:13px;font-weight:bold;min-width:30px;text-align:right;}

.row{display:flex;justify-content:space-between;padding:7px 8px;border-bottom:1px dashed rgba(255,255,255,0.06);font-size:13px;}
.row:last-child{border-bottom:none;}
.row span:first-child{color:#94a3b8;}
.price-highlight{color:#38bdf8;font-weight:bold;}
.avg-up{color:#22c55e;}
.avg-down{color:#ef4444;}
.oi-val{color:#a78bfa;}

.timestamp{text-align:center;color:#475569;font-size:11px;margin-top:20px;}
</style>
</head>
<body>

<div class="header">
  <div>
    <div class="title">NSE OPTIONS DASHBOARD</div>
    <div class="sub">Live Options — Munafa Score &amp; Signal</div>
  </div>
  <button onclick="loadData()" class="refresh-btn">⟳ Refresh</button>
</div>

<div class="tabs">
  <div class="tab active" onclick="switchTab('CE',this)">CALL (CE)</div>
  <div class="tab" onclick="switchTab('PE',this)">PUT (PE)</div>
</div>

<div class="loader" id="loader">Fetching live options data...</div>
<div id="error" class="error" style="display:none"></div>
<div class="grid" id="grid"></div>
<div class="timestamp" id="ts"></div>

<script>
let currentTab = 'CE';
let allData = {CE:[], PE:[]};

function switchTab(tab, el){
  currentTab = tab;
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  el.classList.add('active');
  renderCards(allData[tab]);
}

function munafaColor(score){
  if(score >= 60) return '#22c55e';
  if(score >= 40) return '#facc15';
  return '#ef4444';
}

function signalFromScore(score){
  if(score >= 60) return {label:'BUY', cls:'buy', badge:'badge-buy'};
  if(score >= 40) return {label:'WATCH', cls:'neutral', badge:'badge-neutral'};
  return {label:'SELL', cls:'sell', badge:'badge-sell'};
}

function createCard(item){
  const sig = signalFromScore(item.munafa_score);
  const color = munafaColor(item.munafa_score);
  const avg10cls = item.price > item.avg10 ? 'avg-up' : 'avg-down';
  const avg30cls = item.price > item.avg30 ? 'avg-up' : 'avg-down';
  const avgHcls  = item.price > item.avgH  ? 'avg-up' : 'avg-down';

  return `
  <div class="card ${sig.cls}">
    <div class="option-name">${item.symbol} ${item.strike} ${item.type}</div>
    <div class="expiry">Expiry: ${item.expiry} &nbsp;|&nbsp; Lot: ${item.lot_size}</div>
    <span class="signal-badge ${sig.badge}">${sig.label}</span>

    <div class="munafa-row">
      <span class="munafa-label">Munafa Score</span>
      <div class="munafa-bar-bg"><div class="munafa-bar" style="width:${item.munafa_score}%;background:${color}"></div></div>
      <span class="munafa-score" style="color:${color}">${item.munafa_score}</span>
    </div>

    <div class="row"><span>LTP</span><span class="price-highlight">₹${item.price}</span></div>
    <div class="row"><span>Day Open</span><span>₹${item.day_open}</span></div>
    <div class="row"><span>Day Range</span><span>${item.day_range}</span></div>
    <div class="row"><span>10 Min Avg</span><span class="${avg10cls}">₹${item.avg10}</span></div>
    <div class="row"><span>30 Min Avg</span><span class="${avg30cls}">₹${item.avg30}</span></div>
    <div class="row"><span>Hourly Avg</span><span class="${avgHcls}">₹${item.avgH}</span></div>
    <div class="row"><span>Open Interest</span><span class="oi-val">${item.oi}</span></div>
    <div class="row"><span>Spot Price</span><span>₹${item.spot}</span></div>
  </div>`;
}

function renderCards(data){
  const grid = document.getElementById('grid');
  if(!data || data.length === 0){
    grid.innerHTML = '<div class="error">No data available.</div>';
    return;
  }
  grid.innerHTML = data.map(createCard).join('');
}

async function loadData(){
  document.getElementById('loader').style.display='block';
  document.getElementById('error').style.display='none';
  document.getElementById('grid').innerHTML='';
  document.getElementById('ts').innerText='';

  try{
    const res = await fetch('/api/options');
    const data = await res.json();
    if(data.error){
      document.getElementById('error').innerText = data.error;
      document.getElementById('error').style.display='block';
    } else {
      allData = data;
      renderCards(allData[currentTab]);
      document.getElementById('ts').innerText = 'Last updated: ' + new Date().toLocaleTimeString('en-IN');
    }
  } catch(e){
    document.getElementById('error').innerText = 'Failed to load. Try refreshing.';
    document.getElementById('error').style.display='block';
  }
  document.getElementById('loader').style.display='none';
}

loadData();
</script>
</body>
</html>"""


HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}

def parse_option_page(url, symbol, strike, opt_type):
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text(" ", strip=True)

        def extract(pattern, default="N/A"):
            m = re.search(pattern, text)
            return m.group(1).strip() if m else default

        price    = extract(r'trading at ₹\s*([\d.]+)')
        avg10    = extract(r'10 minute average:\s*₹\s*([\d.]+)')
        avg30    = extract(r'30 minute average:\s*₹\s*([\d.]+)')
        avgH     = extract(r'Hourly average:\s*₹\s*([\d.]+)')
        day_open = extract(r'Day open:\s*₹\s*([\d.]+)')
        day_rng  = extract(r'Day range:\s*([\d.]+ - [\d.]+)')
        oi_raw   = extract(r'Open Interest:\s*([\d,]+(?:\s*\(\w+\))?)')
        munafa   = extract(r'Munafa Value:\s*(\d+)')
        spot     = extract(r'Spot price of [^:]+:\s*([\d.]+)')
        lot      = extract(r'Lot size of \S+ is:\s*([\d,]+)')
        expiry   = extract(r'CE \(CALL\)\s*([\d]+ \w+ \d{4})|PE \(PUT\)\s*([\d]+ \w+ \d{4})')

        # fallback expiry from title
        title = soup.find('title')
        if expiry == "N/A" and title:
            em = re.search(r'(\d{1,2} \w+ \d{4})', title.text)
            expiry = em.group(1) if em else "N/A"

        return {
            "symbol": symbol,
            "strike": strike,
            "type": opt_type,
            "expiry": expiry,
            "price": price,
            "avg10": avg10,
            "avg30": avg30,
            "avgH": avgH,
            "day_open": day_open,
            "day_range": day_rng,
            "oi": oi_raw,
            "munafa_score": int(munafa) if munafa != "N/A" else 50,
            "spot": spot,
            "lot_size": lot
        }
    except Exception as e:
        return None


def get_active_options(opt_type):
    url = "https://munafasutra.com/nse/activeTodayOptions"
    r = requests.get(url, headers=HEADERS, timeout=10)
    soup = BeautifulSoup(r.text, "html.parser")
    links = soup.find_all("a", href=re.compile(rf'/nse/optionsChart/[^/]+/{opt_type}/\d+'))

    seen = set()
    items = []
    for a in links:
        href = a["href"]
        parts = href.strip("/").split("/")
        if len(parts) >= 5:
            symbol = parts[2]
            strike = parts[4]
            key = f"{symbol}-{strike}"
            if key not in seen:
                seen.add(key)
                items.append((symbol, strike, f"https://munafasutra.com{href}"))
        if len(items) >= 12:
            break
    return items


@app.route('/')
def home():
    return HTML


@app.route('/api/options')
def options():
    try:
        ce_list = get_active_options("CE")
        pe_list = get_active_options("PE")

        def fetch_ce(args): return parse_option_page(args[2], args[0], args[1], "CE")
        def fetch_pe(args): return parse_option_page(args[2], args[0], args[1], "PE")

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            ce_results = list(ex.map(fetch_ce, ce_list))
            pe_results = list(ex.map(fetch_pe, pe_list))

        ce_data = [x for x in ce_results if x]
        pe_data = [x for x in pe_results if x]

        # Sort by Munafa Score descending
        ce_data.sort(key=lambda x: x["munafa_score"], reverse=True)
        pe_data.sort(key=lambda x: x["munafa_score"], reverse=True)

        return jsonify({"CE": ce_data, "PE": pe_data})

    except Exception as e:
        return jsonify({"error": f"Failed: {str(e)}"})


if __name__ == '__main__':
    app.run(debug=False)
