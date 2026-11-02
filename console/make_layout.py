"""Generates u400_layout_default.json - Unit 400 graphic laid out like the Station display (1920x1080)."""
import json

E = []


def add(**k):
    k.setdefault('id', f"{k['type']}_{len(E)}")
    E.append(k)


# process lines first (drawn underneath)
for pts in [
    [[120, 870], [205, 870]], [[225, 870], [470, 870]],                       # feed -> E-400
    [[494, 845], [494, 820], [372, 820], [372, 200], [494, 200], [494, 222]],  # E-400 -> E-401 -> R-400 top (schematic)
    [[30, 293], [130, 293]], [[160, 293], [372, 293]],                        # H2 supply
    [[30, 450], [130, 450]], [[160, 450], [333, 450], [333, 497]],            # heat supply -> E-401
    [[110, 525], [305, 525]], [[360, 525], [372, 525]],                       # from E-400 -> E-401
    [[333, 553], [333, 588], [120, 588]],                                     # heat return
    [[517, 255], [843, 255], [843, 360]],                                     # jacket out -> E-410/V-410
    [[640, 255], [640, 310], [690, 310]], [[820, 310], [843, 310]],           # air-fin branch
    [[846, 557], [846, 578]], [[846, 606], [846, 665], [690, 665]],           # V-410 -> P-410 -> FCV411
    [[655, 665], [620, 665]], [[585, 665], [520, 665]],                       # FCV411 -> TCV411 -> jacket in
    [[602, 790], [602, 690]],                                                 # heat supply -> TCV411
    [[846, 665], [846, 800], [880, 800]], [[900, 800], [990, 800]],           # drain -> FCV410 -> effluent
    [[494, 722], [494, 845]],                                                 # R-400 bottom -> E-400
    [[494, 895], [494, 925], [720, 925]], [[770, 925], [960, 925]],           # E-400 -> E-420 -> PCV420
    [[995, 925], [1010, 925], [1010, 385], [1210, 385]],                      # -> V-420
    [[1296, 322], [1296, 437], [1250, 437]],                                  # N2 -> V-420
    [[1097, 560], [1097, 643], [1125, 643]], [[1160, 643], [1190, 643]],      # V-420 -> P-420 -> FCV420
    [[1220, 643], [1240, 643]], [[1373, 643], [1480, 643], [1480, 475]],      # -> filters
    [[1480, 475], [1480, 410], [1720, 410]],                                  # run-down
    [[233, 760], [233, 785], [120, 785]], [[300, 665], [300, 767], [380, 767]], [[408, 767], [494, 767]],
]:
    add(type='line', pts=pts)

# equipment
add(type='vessel', id='R-400', x=470, y=222, w=47, h=500, label='R-400', shape='column')
add(type='vessel', id='V-400', x=192, y=630, w=82, h=130, label='V-400', level='04LI400')
add(type='vessel', id='V-410', x=806, y=362, w=82, h=195, label='V-410', level='04LIC410')
add(type='vessel', id='V-420', x=1052, y=455, w=255, h=105, label='V-420', level='04LIC420', shape='drum')
add(type='vessel', id='F420A', x=1366, y=455, w=64, h=120, label='F420A')
add(type='vessel', id='F420B', x=1530, y=455, w=64, h=120, label='F420B')
add(type='box', id='E-410', x=690, y=272, w=130, h=80, label='E-410 Airfin bank')
for hid, x, y in [('E-401', 333, 525), ('E-400', 494, 870), ('E-420', 743, 925)]:
    add(type='hx', id=hid, x=x, y=y, r=27, label=hid)
add(type='pump', id='P-410', tag='P-410', x=846, y=592)
add(type='pump', id='P-420', tag='P-420', x=1143, y=643)

# valves (tag = controller that drives them)
for vid, tag, x, y in [('04FCV402', '04FIC402', 145, 293), ('04FCV401', '04FIC401', 145, 450),
                       ('04FCV400', '04FIC400', 213, 870), ('04TCV410', '04TIC410', 642, 256),
                       ('04TCV411', '04TIC411', 602, 665), ('04FCV411', '04FIC411', 670, 665),
                       ('04FCV410', '04FIC410', 880, 800), ('04PCV420', '04PIC420', 977, 925),
                       ('04FCV421', '04FIC421', 1349, 322), ('04FCV420', '04FIC420', 1205, 643)]:
    add(type='valve', id=vid, tag=tag, x=x, y=y, label=vid, three_way=(vid == '04TCV411'))
add(type='valve', id='04XZV401', tag='', x=393, y=767, label='04XZV401')

# faceplates (controllers)
for tag, x, y in [('04FIC402', 178, 265), ('04TIC401', 96, 347), ('04FIC401', 178, 421),
                  ('04FIC400', 248, 845), ('04TIC411', 530, 540), ('04FIC411', 700, 637),
                  ('04TIC410', 853, 315), ('04LIC410', 890, 517), ('04FIC410', 833, 700),
                  ('04PIC420', 808, 848), ('04FIC421', 1385, 295), ('04FIC420', 1240, 616)]:
    add(type='fp', id='fp_' + tag, tag=tag, x=x, y=y)

# indicators
for tag, x, y in [('04TI407', 372, 175), ('04TI401', 380, 262), ('04TI402', 380, 345), ('04TI403', 380, 427),
                  ('04TI404', 380, 509), ('04TI405', 380, 577), ('04TI406', 380, 662), ('04TI408', 528, 235),
                  ('04TI412', 718, 468), ('04FI413', 502, 760), ('04TI400', 548, 838), ('04AT400', 548, 915),
                  ('04TI420', 776, 930), ('04AT420', 1078, 522), ('04LIC420', 1176, 522), ('04LI400', 108, 730),
                  ('04PT424', 1612, 432), ('04dP420', 1612, 505), ('04PT423', 1612, 576), ('04FIQ420', 1720, 443),
                  ('01PI121', 90, 187), ('01PI122', 90, 228), ('05PIC511', 35, 902)]:
    add(type='val', id='v_' + tag, tag=tag, x=x, y=y)

for t, x, y in [('Service Air:', 28, 180), ('Instrument Air:', 22, 222), ('H2 supply', 30, 298),
                ('Heat Supply', 30, 455), ('From E-400', 32, 530), ('Heat Return', 42, 592),
                ('Unit 400 Feed', 33, 875), ('Sewer', 80, 790), ('Water effluent', 905, 805),
                ('Heat supply', 503, 795), ('Nitrogen Supply', 1575, 326), ('Unit 420 Run Down', 1722, 414),
                ('CW', 665, 874), ('CW ret.', 765, 983), ('To Safe Location', 1240, 188), ('Mix Temp', 728, 500)]:
    add(type='text', id='t_' + t.replace(' ', '_'), text=t, x=x, y=y)
add(type='button', id='btn_restart', text='Restart Run', cmd='restart_run', x=1470, y=172)

json.dump(dict(width=1920, height=1080, elements=E), open('u400_layout_default.json', 'w'), indent=1)
print(len(E), 'elements')
