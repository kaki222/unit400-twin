"""UNIT400-TWIN M3: catalyst screening grids. Writes screening_*.csv and prints maps.
Usage: python3 scenario_screening.py [quick]   (quick = smaller grids, ~3 min)"""
import csv, sys, time
import catalyst as C
import screening as S

quick = len(sys.argv) > 1 and sys.argv[1] == 'quick'
lib = C.load_library('catalysts.json')
base = lib['mimic_baseline']
SPS = [115, 125, 135, 145] if quick else [115, 125, 135, 145, 155]
ACTS = [60, 80, 100, 120] if quick else [50, 60, 70, 80, 90, 100, 110, 120]
F0 = S.FEED
FEEDS = [int(F0 * k) for k in ((0.7, 1.0, 1.25) if quick else (0.6, 0.8, 1.0, 1.25, 1.45))]
SYM = {'OK': ' OK ', 'LOW': ' .. ', 'HOT': ' !! '}


def save(name, rows):
    with open('screening_%s.csv' % name, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)


def grid(title, rowkey, rowvals, make):
    rows = []
    print('\n%s\n%14s' % (title, rowkey) + ''.join('%8s' % ('jkt %d' % s) for s in SPS))
    for rv in rowvals:
        line = '%14s' % rv
        for sp in SPS:
            r = make(rv, sp); rows.append(r)
            line += '%4s%4.0f' % (SYM[r['result']], r['at400'] if r['result'] != 'HOT' else r['peak'])
        print(line, flush=True)
    return rows


t0 = time.time()
print('OK = AT400 <= %.0f %% and hot spot <= %.0f C;  .. = conversion lost;  !! = hot spot > limit' % (S.SPEC_AT400, S.HOT_LIMIT))
print('number = AT400 % (OK/..) or peak hot spot C (!!)')

A = grid('A  catalyst activity x jacket inlet SP (feed %d l/h)' % S.FEED + '', 'activity %', ACTS,
         lambda a, sp: S.screen_point(C.CatalystProfile('act%d' % a, activity_pct=a), sp))
save('activity', A)
B = grid('B  feed rate x jacket inlet SP (baseline catalyst)', 'feed l/h', FEEDS,
         lambda f, sp: S.screen_point(base, sp, feed=f))
save('feed', B)
names = [n for n, p in lib.items() if p.kd_per_h == 0]
Cr = grid('C  catalyst type x jacket inlet SP (feed %d l/h)' % S.FEED + '', 'profile', names,
          lambda n, sp: S.screen_point(lib[n], sp))
save('profiles', Cr)

print('\nD  deactivation: hours on spec (AT400 <= %.0f %%) at feed %d l/h' % (S.SPEC_AT400, S.FEED))
KDS = [0.02, 0.05, 0.1]
DSP = [125, 135, 145]
print('%14s' % 'kd per h' + ''.join('%8s' % ('jkt %d' % s) for s in DSP))
D = []
for kd in KDS:
    line = '%14s' % kd
    for sp in DSP:
        t_lost, trail = S.time_on_spec(C.CatalystProfile('kd%g' % kd, kd_per_h=kd), sp, hours=4 if quick else 8)
        txt = 'never' if t_lost is None and not trail else ('>%dh' % (4 if quick else 8) if t_lost is None else '%.1f' % t_lost)
        D.append(dict(kd_per_h=kd, jacket_sp=sp, hours_on_spec=txt)); line += '%8s' % txt
    print(line, flush=True)
save('deactivation', D)
print('\nrun time %.1f min; CSV files screening_*.csv written' % ((time.time() - t0) / 60))
