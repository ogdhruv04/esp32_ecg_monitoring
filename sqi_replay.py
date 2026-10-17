#!/usr/bin/env python3
# Replay the APP's quality gate (SignalQuality.kt) on the dual03 recordings:
# causal filter -> 0.6 s rolling-median baseline removal (display buffer, which is
# what assess() is handed) ; pSQI = energy(5-15 Hz RBJ biquads) / energy(display)
import numpy as np, sys
from scipy import signal as sps
from scipy.ndimage import median_filter
FS=256.0; WIN=int(sys.argv[1]) if len(sys.argv)>1 else 1280
def load(p, skip=10):
    r=np.genfromtxt(p,delimiter=",",names=True,dtype=None,encoding="utf-8",invalid_raise=False)
    return r["value"].astype(float)[int(skip*FS):]
def causal(x):
    y=sps.sosfilt(sps.butter(4,0.5,"highpass",fs=FS,output="sos"),x)
    for f in (50.,100.):
        b,a=sps.iirnotch(f,30.,fs=FS); y=sps.lfilter(b,a,y)
    return sps.sosfilt(sps.butter(4,40.,"lowpass",fs=FS,output="sos"),y)
def bp(x):
    b1,a1=sps.butter(2,5.0,"highpass",fs=FS); b2,a2=sps.butter(2,15.0,"lowpass",fs=FS)
    return sps.lfilter(b2,a2,sps.lfilter(b1,a1,x))
B=sys.argv[2] if len(sys.argv)>2 else "captures/20260929_163314_dual03_both3wire_c3chest_wroomfinger"
print(f"window {WIN} samples = {WIN/FS:.1f} s, stepped every 1 s")
for name,path in (("chest",B+"_ring.csv"),("finger",B+"_ref.csv")):
    f=causal(load(path)); disp=f-median_filter(f,size=int(.6*FS),mode="nearest"); q=bp(f)
    lv=[]; ks=[]; ps=[]
    for e in range(WIN,len(f),int(FS)):
        d=disp[e-WIN:e]; qq=q[e-WIN:e]
        m=d.mean(); m2=((d-m)**2).mean(); k=((d-m)**4).mean()/m2**2
        p=min(1,(qq**2).sum()/(d**2).sum())
        ks.append(k); ps.append(p)
        lv.append("GOOD" if k>=5 and p>=.10 else "FAIR" if k>=3.5 and p>=.05 else "POOR")
    lv=np.array(lv)
    print(f"  {name:6} kSQI median {np.median(ks):5.1f}  pSQI median {np.median(ps):.3f}   "
          f"GOOD {np.mean(lv=='GOOD')*100:5.1f}%  FAIR {np.mean(lv=='FAIR')*100:5.1f}%  POOR {np.mean(lv=='POOR')*100:5.1f}%"
          f"   -> HR shown {np.mean(lv!='POOR')*100:.0f}% of the time, RMSSD {np.mean(lv=='GOOD')*100:.0f}%")
