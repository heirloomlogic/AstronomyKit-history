"""Rational coefficient enclosures for the selected barycentric apparent Sun model."""
from fractions import Fraction as Q
import re
import struct
from numerics import ROOT, ENGINE, sqrt_interval, earth_model, table_payload

SUN_PATH = ENGINE+'Gravity/Generated/DE441/PlutoDE441SunData.swift'
TDB_PATH = ENGINE+'Moon/Generated/TDBTerms.swift'
PATHS = [SUN_PATH,TDB_PATH,ENGINE+'Moon/EngineTDB.swift',ENGINE+'Moon/EngineFrameBias.swift',
         ENGINE+'Gravity/EnginePlutoDE441.swift',ENGINE+'Positions/EngineApparentPlace.swift',
         ENGINE+'Positions/EngineApparentKinematics.swift',ENGINE+'Positions/EngineApparentComposition.swift',
         ENGINE+'Positions/EngineApparentObserver.swift','Scripts/solar-numerics/apparent_bounds.py',
         'Sources/AstronomyKit/Resources/ModelTables/pluto-de441-sun.bin','Scripts/model_resource.py']


def clock_bounds(limit=Q(37002)):
    text = (ROOT/TDB_PATH).read_text()
    rows = [[Q(float(x)) for x in row.split(',')] for row in re.findall(r'Term\(([^)]+)\)',text)]
    if len(rows) != 787:
        raise ValueError('TDB coefficient layout changed')
    t = limit/365250
    values = [Q(0),Q(0),Q(0)]
    for power,(lo,hi) in enumerate([(0,474),(474,679),(679,764),(764,784),(784,787)]):
        for amplitude,frequency,phase in rows[lo:hi]:
            a,w = abs(amplitude),abs(frequency)
            values[0] += a*t**power
            values[1] += a*(w*t**power+(power*t**(power-1) if power else 0))
            values[2] += a*(w*w*t**power+(2*power*w*t**(power-1) if power else 0)
                            +(power*(power-1)*t**(power-2) if power>1 else 0))
    for a,w in [('0.00065e-6','6069.776754'),('0.00033e-6','213.299095'),
                ('-0.00196e-6','6208.294251'),('-0.00173e-6','74.781599')]:
        a,w=abs(Q(float(a))),abs(Q(float(w)))
        for order in range(3):
            values[order] += a*w**order
    a=Q(float('0.03638e-6'))
    values[0]+=a*t*t
    values[1]+=2*a*t
    values[2]+=2*a
    return {'offsetDays':values[0]/86400,'rateDeparture':values[1]/(365250*86400),
            'accelerationPerDay':values[2]/(365250**2*86400)}


def solar_bounds(lower=Q(-37002), upper=Q(37002)):
    text = (ROOT/SUN_PATH).read_text()
    start,width,count = re.search(r'start: ([^,]+), days: ([^,]+), recordCount: ([^,]+),',text).groups()
    start,width,count=Q(start),Q(width),int(count)
    data=table_payload(SUN_PATH,text)
    if len(data)!=48*(count+1):
        raise ValueError('Solar data size changed')
    clocks=clock_bounds(max(abs(lower),abs(upper)))
    first=(lower-clocks['offsetDays']-start)//width
    last=(upper+clocks['offsetDays']-start)//width
    if not 0<=first<=last<count:
        raise ValueError('Solar source coverage does not enclose clock padding')
    maxima=[Q(0),Q(0),Q(0)]
    au=Q('149597870.700')
    for record in range(first,last+1):
        left=list(map(Q,struct.unpack_from('<6d',data,record*48)))
        right=list(map(Q,struct.unpack_from('<6d',data,(record+1)*48)))
        bounds=[[],[],[]]
        for axis in range(3):
            pl,pr=left[axis],right[axis]
            dl,dr=left[axis+3]*width/2,right[axis+3]*width/2
            c2=(dr-dl)/8
            c3=(dr+dl-(pr-pl))/16
            c=[(pr+pl)/2-c2,(pr-pl)/2-c3,c2,c3]
            bounds[0].append(sum(map(abs,c))/au)
            bounds[1].append(sum(k*k*abs(a) for k,a in enumerate(c))*2/width/au)
            bounds[2].append((4*abs(c2)+24*abs(c3))*4/width**2/au)
        for order in range(3):
            maxima[order]=max(maxima[order],sum(x*x for x in bounds[order]))
    # Frame bias is an orthogonal product of elementary rotations in the mathematical model.
    radius,speed,acceleration=[sqrt_interval(x)[1] for x in maxima]
    q=clocks['rateDeparture']
    return {'radiusAU':radius,'speedTDB':speed,'speedTT':speed*(1+q),
            'accelerationTT':acceleration*(1+q)**2+speed*clocks['accelerationPerDay'],
            'firstRecord':Q(first),'lastRecord':Q(last),'recordCount':Q(last-first+1),
            'sourceStartTDB':start,'sourceStopTDB':start+count*width,**clocks}


def earth_acceleration_bound():
    degree,width,start,stop,values=earth_model()
    n=degree+1
    maximum=Q(0)
    for first in range(0,len(values),3*n):
        axes=[]
        for axis in range(3):
            # max |T_k''| = k^2(k^2-1)/3 on [-1,1].
            axes.append(sum(Q(k*k*(k*k-1),3)*abs(Q(a))
                            for k,a in enumerate(values[first+axis*n:first+(axis+1)*n]))/(width/2)**2)
        maximum=max(maximum,sum(a*a for a in axes))
    return sqrt_interval(maximum)[1]*Q('1.000001')


def earth_velocity_join_bound():
    degree,width,start,stop,values=earth_model()
    n=degree+1
    maximum=Q(0)
    for segment in range(1,len(values)//(3*n)):
        differences=[]
        for axis in range(3):
            left=values[((segment-1)*3+axis)*n:((segment-1)*3+axis+1)*n]
            right=values[(segment*3+axis)*n:(segment*3+axis+1)*n]
            dl=sum(k*k*Q(a) for k,a in enumerate(left))*2/width
            dr=sum((-1)**(k-1)*k*k*Q(a) for k,a in enumerate(right) if k)*2/width
            differences.append(dl-dr)
        maximum=max(maximum,sum(d*d for d in differences))
    return sqrt_interval(maximum)[1]*Q('1.000001')


def orientation_bounds():
    """Operator-norm first/second bounds for the actual site rotation, per TT day.

    Products of rotations use ||(AB)''|| <= ||A''||+2||A'|| ||B'||+||B''||.
    Normalized equinox x=v/|v| uses ||x''|| <= ||v''||/|v|+3||v'||²/|v|².
    """
    import precession_bounds as pre
    from numerics import unpack
    t=Q('1.02')
    pi=pre.pi_interval().hi
    arc=pi/648000
    tables=pre.tables()
    enclosure=pre.enclose(t,data=tables)
    def polynomial(c,order):
        import math
        return sum(abs(a)*Q(math.factorial(k),math.factorial(k-order))*t**(k-order)
                   for k,a in enumerate(c) if k>=order)
    pole=[]
    for name,radicand in [('equator',enclosure['equatorRadicandLower']),('ecliptic',enclosure['eclipticRadicandLower'])]:
        polys,periodic=tables[name]
        derivatives=[]
        for order in [1,2]:
            axes=[]
            for axis in [0,1]:
                periodic_bound=sum((abs(row[axis+1])+abs(row[axis+3]))*(2*pi/abs(row[0]))**order for row in periodic)
                axes.append((polynomial(polys[axis],order)+periodic_bound)*arc/36525**order)
            derivatives.append(axes)
        a,b=derivatives[0]
        aa,bb=derivatives[1]
        z=sqrt_interval(radicand)[0]
        first=a+b+(a+b)/z
        second=aa+bb+(a*a+b*b+aa+bb)/z+(a+b)**2/z**3
        pole.append((first,second))
    (p1,p2),(q1,q2)=pole
    cross_min=enclosure['crossNormLower']
    v1=p1+q1
    v2=p2+q2+2*p1*q1
    x1=v1/cross_min
    x2=v2/cross_min+3*v1*v1/cross_min**2
    pre1=x1+(p1+x1)+p1
    pre2=x2+(p2+x2+2*p1*x1)+p2
    eps1=v1/cross_min
    eps2=v2/cross_min+v1*v1/cross_min**3
    source=(ROOT/(ENGINE+'Orientation/EngineNutation.swift')).read_text()
    block=source.split('luniSolarArguments: [[Double]] = [',1)[1].split('    ]',1)[0]
    polys=[[Q(float(x.replace('_',''))) for x in row.split(',')] for row in re.findall(r'\[([-+0-9_., ]+)\]',block)]
    lunar1=[polynomial(c,1)*arc/36525 for c in polys]
    lunar2=[polynomial(c,2)*arc/36525**2 for c in polys]
    block=source.split('planetaryArguments:',1)[1].split('    ]',1)[0]
    linear=[abs(Q(float(row.split(',')[1].replace('_',''))))/36525 for row in re.findall(r'\(([-+0-9_., ]+)\),',block)]
    gp=re.search(r'generalPrecession = \(linear: ([0-9_.]+), quadratic: ([0-9_.]+)\)',source)
    g0,g1=[abs(Q(float(x.replace('_','')))) for x in gp.groups()]
    planetary1=linear+[(g0+2*g1*t)/36525]
    planetary2=[Q(0)]*12+[2*g1/36525**2]
    table=(ROOT/(ENGINE+'Orientation/Generated/IAU2000ATerms.swift')).read_text()
    ls,pl=table.split('static let planetaryTerms',1)
    ls,pl=list(map(Q,unpack(ls))),list(map(Q,unpack(pl)))
    terms=[(ls[i:i+11],5,lunar1,lunar2,True) for i in range(0,len(ls),11)]
    terms += [(pl[i:i+17],13,planetary1,planetary2,False) for i in range(0,len(pl),17)]
    bounds=[[Q(0)]*3 for _ in range(2)]
    for row,width,r1,r2,is_lunar in terms:
        w=sum(abs(n)*v for n,v in zip(row[:width],r1))
        w2=sum(abs(n)*v for n,v in zip(row[:width],r2))
        if is_lunar:
            ps,pst,pc,ec,ect,es=row[width:]
            amplitudes=[(abs(ps)+abs(pst)*t+abs(pc),abs(pst)/36525),
                        (abs(ec)+abs(ect)*t+abs(es),abs(ect)/36525)]
        else:
            ps,pc,es,ec=row[width:]
            amplitudes=[(abs(ps)+abs(pc),Q(0)),(abs(es)+abs(ec),Q(0))]
        for total,(a,d) in zip(bounds,amplitudes):
            total[0]+=a
            total[1]+=a*w+d
            total[2]+=a*(w*w+w2)+2*d*w
    factor,j2=[abs(Q(re.search(r'static let '+key+r' = (\S+)\n',table)[1])) for key in ['longitudeFactor','j2Rate']]
    final=[]
    for i,(value,first,second) in enumerate(bounds):
        scale=1+(factor if i==0 else 0)+j2*t
        unit=arc/Q(10**7)
        final.append((value*scale*unit,(first*scale+value*j2/36525)*unit,
                      (second*scale+2*first*j2/36525)*unit))
    (psi,psi1,psi2),(_,deps1,deps2)=final
    n1=2*eps1+psi1+deps1
    n2=2*eps2+psi2+deps2+n1*n1
    rotation1=pre1+n1
    rotation2=pre2+n2+2*pre1*n1
    # Complementary arguments have identical derivatives to their nutation counterparts.
    r1=lunar1+[linear[5],linear[6],planetary1[-1]]
    r2=lunar2+[Q(0),Q(0),planetary2[-1]]
    text=(ROOT/(ENGINE+'Orientation/Generated/EquinoxComplementaryTerms.swift')).read_text()
    rows=[[Q(x.strip().replace('_','')) for x in row.split(',')] for row in re.findall(r'ComplementaryTerm\(([^)]+)\)',text)]
    comp1=comp2=Q(0)
    for index,row in enumerate(rows):
        a=abs(row[8])+abs(row[9])
        w=sum(abs(n)*v for n,v in zip(row[:8],r1))
        w2=sum(abs(n)*v for n,v in zip(row[:8],r2))
        scale=t if index==33 else 1
        d=Q(1,36525) if index==33 else 0
        comp1+=a*(scale*w+d)*arc
        comp2+=a*(scale*(w*w+w2)+2*d*w)*arc
    sidereal=[Q(x) for x in ['.014506','4612.156534','1.3915817','-.00000044','-.000029956','-.0000000368']]
    sid1=polynomial(sidereal,1)*arc/36525+psi1+psi*eps1+comp1
    sid2=polynomial(sidereal,2)*arc/36525**2+psi2+2*psi1*eps1+psi*(eps2+eps1*eps1)+comp2
    omega=2*pi*(1+Q('0.00273781191135448'))
    angle1=omega+sid1
    # Site motion is R^T applied to a vector rotating about the date z axis.
    return {'rotationRate':rotation1,'rotationAcceleration':rotation2,
            'siderealTTRate':sid1,'siderealTTAcceleration':sid2,'eraRate':omega,
            'siteSpeedPerRadius':angle1+rotation1,
            'siteAccelerationPerRadius':sid2+angle1**2+2*rotation1*angle1+rotation2}
