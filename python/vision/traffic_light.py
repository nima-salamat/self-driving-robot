"""HSV traffic-light classifier with legacy tuple API."""
import logging
from collections import deque
import cv2
import numpy as np
import modes.city.config_city as config_city
logger=logging.getLogger(__name__)
class TrafficLightDetector:
    def __init__(self,config=None): self.config=config
    def _get(self,key,default): return getattr(self.config or config_city,key,default)
    def detect(self,frame):
        if not isinstance(frame,np.ndarray) or frame.size==0 or frame.ndim!=3 or frame.shape[2]!=3:return None,None
        h,w=frame.shape[:2];roi=tuple(self._get(k,d) for k,d in (("TL_TOP_ROI",0.),("TL_BOTTOM_ROI",1.),("TL_LEFT_ROI",0.),("TL_RIGHT_ROI",1.)))
        if not all(isinstance(v,(int,float)) and not isinstance(v,bool) for v in roi):return None,None
        t,b,l,r=roi
        if not (0<=t<b<=1 and 0<=l<r<=1):logger.warning("Invalid traffic-light ROI");return None,None
        y1,y2,x1,x2=int(t*h),int(b*h),int(l*w),int(r*w)
        if y1>=y2 or x1>=x2 or y2>h or x2>w:return None,None
        crop=frame[y1:y2,x1:x2]
        if crop.size==0:return None,None
        debug=crop.copy() if self._get("DEBUG",False) else None;hsv=cv2.cvtColor(crop,cv2.COLOR_BGR2HSV)
        sat=int(self._get("TL_MIN_SATURATION",50));val=int(self._get("TL_MIN_VALUE",50));area_min=float(self._get("TL_MIN_CONTOUR_AREA",5));bright=float(self._get("TL_MIN_ACTIVE_BRIGHTNESS",180))
        ranges=(("RED",self._get("TL_RED_HSV_RANGES",(((0,100,100),(10,255,255)),((170,100,100),(180,255,255))))),("GREEN",self._get("TL_GREEN_HSV_RANGES",(((40,50,50),(90,255,255)),)))
        evidence={}
        for name,rs in ranges:
            mask=np.zeros(hsv.shape[:2],np.uint8)
            for lo,hi in rs:
                lo=(int(lo[0]),max(int(lo[1]),sat),max(int(lo[2]),val));mask=cv2.bitwise_or(mask,cv2.inRange(hsv,np.array(lo,np.uint8),np.array(hi,np.uint8)))
            contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE);found=[]
            for c in contours:
                if cv2.contourArea(c)<area_min:continue
                cm=np.zeros(mask.shape,np.uint8);cv2.drawContours(cm,[c],-1,255,-1);v=cv2.mean(hsv[:,:,2],mask=cm)[0]
                if v>=bright:found.append((cv2.contourArea(c),v,c))
            if found:evidence[name]=max(found,key=lambda x:x[0])
        color=next(iter(evidence)) if len(evidence)==1 else None
        if debug is not None:
            for name,(_,v,c) in evidence.items():
                (cx,cy),radius=cv2.minEnclosingCircle(c);cv2.circle(debug,(int(cx),int(cy)),max(1,int(radius)),(0,255,255),2)
                cv2.putText(debug,f"{name} V={v:.0f}",(int(cx),max(12,int(cy)-8)),cv2.FONT_HERSHEY_SIMPLEX,.45,(0,255,255),1)
        return color,debug
class GreenConfirmationWindow:
    def __init__(self,window_size=10,required_green=8):
        if not isinstance(window_size,int) or isinstance(window_size,bool) or window_size<1:raise ValueError("window_size must be positive")
        if not isinstance(required_green,int) or isinstance(required_green,bool) or not 1<=required_green<=window_size:raise ValueError("required_green must be within window")
        self.window_size,self.required_green=window_size,required_green;self.observations=deque(maxlen=window_size);self.last_frame_token=None
    def reset(self):self.observations.clear();self.last_frame_token=None
    def observe(self,color,frame_token):
        if frame_token is None or frame_token==self.last_frame_token:return self.confirmed
        self.last_frame_token=frame_token;self.observations.append(color if color in ("RED","GREEN") else None);return self.confirmed
    @property
    def green_count(self):return sum(v=="GREEN" for v in self.observations)
    @property
    def confirmed(self):return bool(self.observations and self.observations[-1]=="GREEN" and self.green_count>=self.required_green)
