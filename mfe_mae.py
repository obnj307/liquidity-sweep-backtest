#!/usr/bin/env python3
"""BTCUSDT M5 V2 sweep+CHoCH: 48-bar MFE/MAE and first-touch SL/TP study.
Standard library only. Research only, not an execution system.
"""
import argparse, csv, json, math
from pathlib import Path
from statistics import median
from backtest_v2 import load, atr14, setups, BAR_MS

HORIZON=48
SL_PCTS=(0.10,0.20,0.30,0.50,0.75,1.00)
TP_PCTS=(0.20,0.30,0.50,0.75,1.00,1.50,2.00)

def save(path,rows,fields):
    with open(path,'w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)

def round6(x): return round(x,6)

def excursion(d,signal,window):
    idx=signal['confirm']+1
    if idx+window>len(d):return None  # complete horizon only
    entry=d[idx][1]
    if entry<=0:return None
    side=signal['side']; direction=1 if side=='BUY' else -1
    path=d[idx:idx+window]
    # Extremes are relative to the next candle OPEN, and include the entry candle.
    fav=[((b[2]-entry) if direction==1 else (entry-b[3]))/entry*100 for b in path]
    adv=[((entry-b[3]) if direction==1 else (b[2]-entry))/entry*100 for b in path]
    imax=max(range(len(path)),key=lambda i:fav[i]);imin=max(range(len(path)),key=lambda i:adv[i])
    return {'entry_idx':idx,'entry':entry,'side':side,'direction':direction,
            'mfe_pct':max(0,fav[imax]),'mae_pct':max(0,adv[imin]),
            'mfe_bar':imax+1,'mae_bar':imin+1,'path':path}

def first_touch(info,sl_pct,tp_pct,fee_bps,slip_bps):
    """Percentages from entry. Execution modeled as fixed round-trip basis-point cost.
    SL-first when both touched in same OHLC bar; OHLC cannot resolve intrabar ordering.
    """
    entry=info['entry']; direction=info['direction']
    sl=entry*(1-direction*sl_pct/100)
    tp=entry*(1+direction*tp_pct/100)
    reason='TIME'; ambiguous=False; exit_bar=len(info['path']);exit_price=info['path'][-1][4]
    for i,b in enumerate(info['path'],1):
        hit_sl=(b[3]<=sl if direction==1 else b[2]>=sl)
        hit_tp=(b[2]>=tp if direction==1 else b[3]<=tp)
        if hit_sl or hit_tp:
            ambiguous=hit_sl and hit_tp
            reason='SL' if hit_sl else 'TP'
            exit_price=sl if hit_sl else tp
            exit_bar=i
            break
    gross_pct=direction*(exit_price-entry)/entry*100
    cost_pct=2*(fee_bps+slip_bps)/100
    return {'outcome':reason,'ambiguous':int(ambiguous),'exit_bar':exit_bar,
            'gross_pct':round6(gross_pct),'net_pct':round6(gross_pct-cost_pct)}

def summarize_grid(rows):
    total=len(rows);wins=sum(r['net_pct']>0 for r in rows)
    gains=sum(max(0,r['net_pct']) for r in rows)
    losses=-sum(min(0,r['net_pct']) for r in rows)
    return {'trades':total,'net_win_rate_pct':round(100*wins/total,2) if total else None,
            'profit_factor':round(gains/losses,4) if losses else None,
            'avg_net_pct':round(sum(r['net_pct'] for r in rows)/total,5) if total else None,
            'tp_first':sum(r['outcome']=='TP' for r in rows),
            'sl_first':sum(r['outcome']=='SL' for r in rows),
            'time_exit':sum(r['outcome']=='TIME' for r in rows),
            'ambiguous_same_bar':sum(r['ambiguous'] for r in rows)}

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--csv',default='btc_m5.csv')
    p.add_argument('--out',default='results')
    p.add_argument('--fee-bps',type=float,default=6.)
    p.add_argument('--slippage-bps',type=float,default=2.)
    args=p.parse_args()
    if args.fee_bps<0 or args.slippage_bps<0: p.error('Costs must be nonnegative')
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    d=load(args.csv); a=atr14(d)
    split=int(len(d)*.7)
    signal_rows=[];grid_rows=[];overview=[]
    for window in (100,500):
        sig=setups(d,a,window=window)
        observations=[]
        for s in sig:
            info=excursion(d,s,HORIZON)
            if info is None:continue
            # Assign to train/test by entry; require the FULL 4h window in segment.
            segment='train' if info['entry_idx']<split else 'test'
            if segment=='train' and info['entry_idx']+HORIZON>split:continue
            base={'segment':segment,'window':window,'side':info['side'],
                  'sweep_time':d[s['sweep']][0], 'confirm_time':d[s['confirm']][0],
                  'entry_time':d[info['entry_idx']][0], 'entry':round6(info['entry']),
                  'mfe_pct':round6(info['mfe_pct']),'mae_pct':round6(info['mae_pct']),
                  'mfe_usdt':round6(info['entry']*info['mfe_pct']/100),
                  'mae_usdt':round6(info['entry']*info['mae_pct']/100),
                  'mfe_minutes':info['mfe_bar']*5,'mae_minutes':info['mae_bar']*5,
                  'mfe_before_mae':int(info['mfe_bar']<info['mae_bar'])}
            signal_rows.append(base);observations.append((segment,info))
        for segment in ('train','test'):
            obs=[info for seg,info in observations if seg==segment]
            overview.append({'segment':segment,'window':window,'signals':len(obs),
                 'median_mfe_pct':round(median(x['mfe_pct'] for x in obs),5) if obs else None,
                 'median_mae_pct':round(median(x['mae_pct'] for x in obs),5) if obs else None,
                 'median_minutes_to_mfe':median(x['mfe_bar']*5 for x in obs) if obs else None,
                 'median_minutes_to_mae':median(x['mae_bar']*5 for x in obs) if obs else None})
            for sl in SL_PCTS:
                for tp in TP_PCTS:
                    trials=[first_touch(x,sl,tp,args.fee_bps,args.slippage_bps) for x in obs]
                    grid_rows.append({'segment':segment,'window':window,'sl_pct':sl,'tp_pct':tp,
                                      **summarize_grid(trials)})
    save(out/'excursions.csv',signal_rows,['segment','window','side','sweep_time','confirm_time','entry_time','entry','mfe_pct','mae_pct','mfe_usdt','mae_usdt','mfe_minutes','mae_minutes','mfe_before_mae'])
    save(out/'sl_tp_grid.csv',grid_rows,['segment','window','sl_pct','tp_pct','trades','net_win_rate_pct','profit_factor','avg_net_pct','tp_first','sl_first','time_exit','ambiguous_same_bar'])
    save(out/'overview.csv',overview,['segment','window','signals','median_mfe_pct','median_mae_pct','median_minutes_to_mfe','median_minutes_to_mae'])
    print(json.dumps({'candles':len(d),'signals_analyzed':len(signal_rows),'grid_rows':len(grid_rows),'out':str(out)},indent=2))
    for x in overview:print(json.dumps(x))

if __name__=='__main__':main()
