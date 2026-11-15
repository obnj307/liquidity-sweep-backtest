#!/usr/bin/env python3
"""BTCUSDT M5 liquidity sweep research backtest; informational, not a trading bot.
Python 3.11 standard library only. Download Bitget USDT perpetual history or load CSV.
"""
import argparse, csv, json, math, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BAR_MS=300000
URL='https://api.bitget.com/api/v2/mix/market/history-candles'

def download(days, out):
    now=int(time.time()*1000)//BAR_MS*BAR_MS
    earliest=0 if days==0 else now-days*86400000
    end=now
    found={}
    empty=0
    while end>earliest:
        params={'symbol':'BTCUSDT','productType':'USDT-FUTURES','granularity':'5m','endTime':str(end),'limit':'200'}
        req=Request(URL+'?'+urlencode(params),headers={'User-Agent':'LiquiditySweepResearch/1.0'})
        for retry in range(5):
            try:
                with urlopen(req,timeout=30) as r: obj=json.load(r)
                if obj.get('code')!='00000': raise RuntimeError(str(obj))
                break
            except Exception:
                if retry==4: raise
                time.sleep(2**retry)
        rows=obj.get('data') or []
        if not rows:
            empty+=1
            if empty>=3: break
            end-=200*BAR_MS
            continue
        empty=0
        timestamps=[]
        for r in rows:
            t=int(r[0]);timestamps.append(t)
            if earliest<=t<now and t+BAR_MS<=now:
                found[t]=(t,float(r[1]),float(r[2]),float(r[3]),float(r[4]))
        next_end=min(timestamps)-BAR_MS
        if next_end>=end: raise RuntimeError('Pagination stalled')
        end=next_end
        if len(found)%10000<200: print(f'Downloaded {len(found)} bars, earliest {datetime.fromtimestamp(min(found)/1000,timezone.utc).date()}',flush=True)
        time.sleep(.12)
    data=[found[t] for t in sorted(found)]
    if len(data)<1000: raise RuntimeError(f'Only {len(data)} bars; not enough history')
    with open(out,'w',newline='') as f:
        w=csv.writer(f);w.writerow(['time','open','high','low','close']);w.writerows(data)
    return data

def load(path):
    with open(path,newline='') as f:
        rows=list(csv.DictReader(f))
    data=sorted([(int(r['time']),float(r['open']),float(r['high']),float(r['low']),float(r['close'])) for r in rows])
    if any(b[0]<=a[0] for a,b in zip(data,data[1:])): raise ValueError('Duplicate/nonmonotonic candles')
    return data

def atr14(data):
    out=[None]*len(data);tr=[]
    for i,b in enumerate(data):
        v=max(b[2]-b[3],abs(b[2]-data[i-1][4]),abs(b[3]-data[i-1][4])) if i else b[2]-b[3]
        tr.append(v)
        if i==13:out[i]=sum(tr)/14
        elif i>13:out[i]=(out[i-1]*13+v)/14
    return out

def swings(data,k=3):
    lows=[];highs=[]
    for i in range(k,len(data)-k):
        low=data[i][3];high=data[i][2]
        if all(low<data[j][3] for j in range(i-k,i+k+1) if j!=i):lows.append((i+k,i,low))
        if all(high>data[j][2] for j in range(i-k,i+k+1) if j!=i):highs.append((i+k,i,high))
    return lows,highs

def detect(data,atr,low_swings,high_swings,window,mode):
    """Sweep levels known before current bar; consume level on any touch/breach.
    mode='single' or 'equal': equal requires 2 nearby pivot levels (0.15 ATR).
    """
    import collections
    active_low=collections.deque();active_high=collections.deque()
    li=hi=0;signals=[]
    for i in range(20,len(data)):
        while li<len(low_swings) and low_swings[li][0]<i:
            active_low.append(low_swings[li]);li+=1
        while hi<len(high_swings) and high_swings[hi][0]<i:
            active_high.append(high_swings[hi]);hi+=1
        while active_low and active_low[0][1]<i-window:active_low.popleft()
        while active_high and active_high[0][1]<i-window:active_high.popleft()
        a=atr[i-1]
        if a is None or a<=0:continue
        b=data[i];candidate=[]
        for side,levels in [('BUY',active_low),('SELL',active_high)]:
            for confirm,pivot,price in levels:
                if mode=='equal':
                    matches=sum(1 for _,p,v in levels if p!=pivot and abs(v-price)<=.15*a and abs(p-pivot)>=3)
                    if matches==0:continue
                if side=='BUY':
                    valid=b[3]<=price-.1*a and b[4]>price and b[4]-price<=.5*a
                else:
                    valid=b[2]>=price+.1*a and b[4]<price and price-b[4]<=.5*a
                if valid:
                    candidate.append((side,price,pivot))
        # A price level is consumed after any penetration; no reusing swept liquidity.
        active_low=collections.deque(x for x in active_low if b[3]>=x[2])
        active_high=collections.deque(x for x in active_high if b[2]<=x[2])
        # One signal per bar: prioritize most recent level; skip conflicting directions.
        if candidate and len({c[0] for c in candidate})==1:
            side,level,pivot=max(candidate,key=lambda c:c[2]);signals.append((i,side,level))
    return signals

def simulate(data,signals,rr,fee_bps,slippage_bps,max_hold=48):
    """Entry next bar open; SL at sweep extremum + 0.1 previous ATR not modeled here;
    use sweep candle extreme. Stop first if SL and TP both touched on same candle.
    Only one trade at a time; exit at time limit. Fees on both legs.
    """
    trades=[];free=0;cost=(2*fee_bps+2*slippage_bps)/10000
    for idx,side,level in signals:
        entry_idx=idx+1
        if entry_idx>=len(data) or entry_idx<free:continue
        entry=data[entry_idx][1]
        stop=data[idx][3] if side=='BUY' else data[idx][2]
        risk=entry-stop if side=='BUY' else stop-entry
        if risk<=0 or risk/entry>.05:continue
        target=entry+rr*risk if side=='BUY' else entry-rr*risk
        end=min(len(data)-1,entry_idx+max_hold-1)
        exit_price=data[end][4];reason='TIME';exit_idx=end
        for j in range(entry_idx,end+1):
            hi,lo=data[j][2],data[j][3]
            stop_hit=lo<=stop if side=='BUY' else hi>=stop
            tp_hit=hi>=target if side=='BUY' else lo<=target
            if stop_hit:
                exit_price=stop;reason='SL';exit_idx=j;break
            if tp_hit:
                exit_price=target;reason='TP';exit_idx=j;break
        gross=(exit_price-entry)/entry*(1 if side=='BUY' else -1)
        net=gross-cost
        trades.append({'time':data[idx][0],'side':side,'entry':entry,'exit':exit_price,'reason':reason,'net_pct':net*100,'r':net/(risk/entry)})
        free=exit_idx+1
    return trades

def metrics(trades):
    if not trades:return {'trades':0,'win_rate_pct':None}
    wins=[t for t in trades if t['net_pct']>0];losses=[t for t in trades if t['net_pct']<0]
    equity=1.;peak=1.;maxdd=0
    for t in trades:
        equity*=1+t['net_pct']/100
        peak=max(peak,equity);maxdd=max(maxdd,(peak-equity)/peak)
    gain=sum(t['net_pct'] for t in wins);loss=-sum(t['net_pct'] for t in losses)
    return {'trades':len(trades),'win_rate_pct':round(100*len(wins)/len(trades),2),
      'profit_factor':round(gain/loss,3) if loss else None,
      'avg_net_pct':round(sum(t['net_pct'] for t in trades)/len(trades),4),
      'avg_r':round(sum(t['r'] for t in trades)/len(trades),3),
      'max_drawdown_pct':round(maxdd*100,2),
      'compounded_return_pct':round((equity-1)*100,2)}

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--days',type=int,default=180,help='0 requests all available history; default 180')
    p.add_argument('--csv',default='btc_m5.csv')
    p.add_argument('--reuse',action='store_true',help='Use existing CSV instead of API')
    p.add_argument('--fee-bps',type=float,default=6.,help='Fee per side, basis points; illustrative')
    p.add_argument('--slippage-bps',type=float,default=2.,help='Slippage per side, basis points; illustrative')
    a=p.parse_args()
    data=load(a.csv) if a.reuse else download(a.days,a.csv)
    gaps=sum(b[0]-x[0]!=BAR_MS for x,b in zip(data,data[1:]))
    if gaps:raise RuntimeError(f'{gaps} missing candle intervals: repair dataset before testing')
    atr=atr14(data);lo,hi=swings(data)
    summary=[];alltrades=[]
    for window in (100,500):
        for mode in ('single','equal'):
            sig=detect(data,atr,lo,hi,window,mode)
            for rr in (1.,1.5,2.):
                trades=simulate(data,sig,rr,a.fee_bps,a.slippage_bps)
                m={'window':window,'type':mode,'rr':rr,'signals':len(sig),**metrics(trades)}
                summary.append(m)
                for t in trades:alltrades.append({'window':window,'type':mode,'rr':rr,**t})
                print(json.dumps(m))
    with open('summary.csv','w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(summary[0]));w.writeheader();w.writerows(summary)
    with open('trades.csv','w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(alltrades[0]) if alltrades else ['window','type','rr','time','side','entry','exit','reason','net_pct','r']);w.writeheader();w.writerows(alltrades)
    print(f'Completed: {len(data)} BTC M5 bars; {len(summary)} variants; summary.csv and trades.csv')

if __name__=='__main__':main()
