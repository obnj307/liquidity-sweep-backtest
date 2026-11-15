#!/usr/bin/env python3
"""BTC M5 liquidity sweep + CHoCH research. Standard library only.
Uses existing btc_m5.csv; no trading or Telegram orders.
"""
import argparse, csv, json, math
from collections import deque
from pathlib import Path

BAR_MS = 300000

def load(path):
    with open(path, newline='') as f:
        data = [(int(r['time']), float(r['open']), float(r['high']), float(r['low']), float(r['close'])) for r in csv.DictReader(f)]
    data.sort()
    if len(data) < 1000 or any(b[0]-a[0] != BAR_MS for a,b in zip(data,data[1:])):
        raise ValueError('Missing/duplicate candles or too little history')
    return data

def atr14(d):
    a=[None]*len(d); trs=[]
    for i,b in enumerate(d):
        tr=max(b[2]-b[3],abs(b[2]-d[i-1][4]),abs(b[3]-d[i-1][4])) if i else b[2]-b[3]
        trs.append(tr)
        if i==13:a[i]=sum(trs[:14])/14
        elif i>13:a[i]=(a[i-1]*13+tr)/14
    return a

def pivots(d,k):
    lo=[];hi=[]
    for i in range(k,len(d)-k):
        if all(d[i][3]<d[j][3] for j in range(i-k,i+k+1) if j!=i):lo.append((i+k,i,d[i][3]))
        if all(d[i][2]>d[j][2] for j in range(i-k,i+k+1) if j!=i):hi.append((i+k,i,d[i][2]))
    return lo,hi

def setups(d,atr,window=500,k=5,confirm_bars=6,prominence=.5):
    lows,highs=pivots(d,k)
    active_l=deque();active_h=deque();li=hi=0
    pending=[]; signals=[]
    for i in range(30,len(d)-1):
        while li<len(lows) and lows[li][0]<i:active_l.append(lows[li]);li+=1
        while hi<len(highs) and highs[hi][0]<i:active_h.append(highs[hi]);hi+=1
        while active_l and active_l[0][1]<i-window:active_l.popleft()
        while active_h and active_h[0][1]<i-window:active_h.popleft()
        bar=d[i];a=atr[i-1]
        if not a or a<=0:continue
        # Confirm only against a structure threshold fixed at the sweep candle.
        keep=[]
        for p in pending:
            if i>p['expiry']:continue
            if p['side']=='BUY':
                invalid=bar[3]<=p['stop']; confirmed=bar[4]>p['break']
            else:
                invalid=bar[2]>=p['stop']; confirmed=bar[4]<p['break']
            if invalid:continue
            if confirmed:
                signals.append(dict(p,confirm=i))
            else:keep.append(p)
        pending=keep
        candidates=[]
        for side,levels in (('BUY',active_l),('SELL',active_h)):
            for known,pivot,price in levels:
                # Require a distinct pivot (not a tiny fluctuation around its neighbors).
                local=d[max(0,pivot-k):pivot+k+1]
                strength=(max(x[2] for x in local)-price) if side=='BUY' else (price-min(x[3] for x in local))
                if strength<prominence*a:continue
                if side=='BUY':
                    good=bar[3]<=price-.1*a and price<bar[4]<=price+.5*a
                else:
                    good=bar[2]>=price+.1*a and price>bar[4]>=price-.5*a
                if good:candidates.append((side,pivot,price))
        # Consume levels when touched, even if no signal, preventing repeated sweeps.
        active_l=deque(x for x in active_l if bar[3]>=x[2])
        active_h=deque(x for x in active_h if bar[2]<=x[2])
        if candidates and len({x[0] for x in candidates})==1:
            side,pivot,level=max(candidates,key=lambda x:x[1])
            # The pre-sweep structure is a trailing range, excluding sweep candle.
            lookback=12
            prior=d[max(0,i-lookback):i]
            threshold=max(x[2] for x in prior) if side=='BUY' else min(x[3] for x in prior)
            stop=bar[3]-.1*a if side=='BUY' else bar[2]+.1*a
            pending.append({'sweep':i,'side':side,'level':level,'break':threshold,'stop':stop,'expiry':i+confirm_bars})
    # Deduplicate confirmations if multiple levels lead to the same candle/side.
    unique={}
    for s in signals:unique.setdefault((s['confirm'],s['side']),s)
    return list(unique.values())

def simulate(d,signals,rr,fee_bps=6,slippage_bps=2,max_hold=48,min_target_cost_multiple=2):
    cost=(2*fee_bps+2*slippage_bps)/10000
    trades=[];free=0
    for s in sorted(signals,key=lambda x:x['confirm']):
        idx=s['confirm']+1
        if idx>=len(d) or idx<free:continue
        side=s['side'];entry=d[idx][1];stop=s['stop']
        risk=entry-stop if side=='BUY' else stop-entry
        if risk<=0 or risk/entry>.05:continue
        target=entry+rr*risk if side=='BUY' else entry-rr*risk
        if rr*risk/entry < cost*min_target_cost_multiple:continue
        end=min(len(d)-1,idx+max_hold-1)
        price=d[end][4];reason='TIME';exit_idx=end
        for j in range(idx,end+1):
            high,low=d[j][2],d[j][3]
            sl=(low<=stop) if side=='BUY' else (high>=stop)
            tp=(high>=target) if side=='BUY' else (low<=target)
            if sl:price=stop;reason='SL';exit_idx=j;break
            if tp:price=target;reason='TP';exit_idx=j;break
        net=(price-entry)/entry*(1 if side=='BUY' else -1)-cost
        trades.append({'time':d[s['sweep']][0],'confirm_time':d[s['confirm']][0],'side':side,'entry':entry,'stop':stop,'target':target,'exit':price,'reason':reason,'net_pct':net*100,'r':net/(risk/entry)})
        free=exit_idx+1
    return trades

def metrics(ts):
    if not ts:return {'trades':0,'win_rate_pct':None,'profit_factor':None,'avg_net_pct':None,'max_drawdown_pct':None,'compounded_return_pct':None}
    wins=[t['net_pct'] for t in ts if t['net_pct']>0];losses=[-t['net_pct'] for t in ts if t['net_pct']<0]
    eq=peak=1.;dd=0.
    for t in ts:
        eq*=max(0,1+t['net_pct']/100);peak=max(peak,eq);dd=max(dd,(peak-eq)/peak)
    return {'trades':len(ts),'win_rate_pct':round(100*len(wins)/len(ts),2),'profit_factor':round(sum(wins)/sum(losses),3) if losses else None,'avg_net_pct':round(sum(t['net_pct'] for t in ts)/len(ts),4),'max_drawdown_pct':round(dd*100,2),'compounded_return_pct':round((eq-1)*100,2)}

def write_csv(path,rows,fields):
    with open(path,'w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)

def main():
    p=argparse.ArgumentParser();p.add_argument('--csv',default='btc_m5.csv');p.add_argument('--out',default='.')
    args=p.parse_args();out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    d=load(args.csv);a=atr14(d);split=int(len(d)*.7)
    variants=[];alltrades=[]
    for window in (100,500):
        sig=setups(d,a,window=window)
        for rr in (1.,1.5,2.):
            # Simulate each segment separately: no positions crossing the train/test boundary.
            for segment,start,end in (('train',0,split),('test',split,len(d))):
                subset=[dict(s,confirm=s['confirm']-start,sweep=s['sweep']-start) for s in sig if start<=s['sweep'] and s['confirm']<end-1]
                # Metrics refer to the same original candles; slice only for simulation.
                trades=simulate(d[start:end],subset,rr)
                row={'segment':segment,'window':window,'rr':rr,'signals':len(subset),**metrics(trades)}
                variants.append(row)
                for t in trades:alltrades.append({'segment':segment,'window':window,'rr':rr,**t})
                print(json.dumps(row),flush=True)
    write_csv(out/'summary_v2.csv',variants,list(variants[0]))
    write_csv(out/'trades_v2.csv',alltrades,list(alltrades[0]) if alltrades else ['segment','window','rr','time','confirm_time','side','entry','stop','target','exit','reason','net_pct','r'])
    print('Completed',len(d),'candles, outputs:',out/'summary_v2.csv',out/'trades_v2.csv')
if __name__=='__main__':main()
