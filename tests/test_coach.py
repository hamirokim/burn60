#!/usr/bin/env python3
"""Adaptive coach (spec v0.2) tests: rule thresholds, priority, weekly cap, backup, UI smoke.
Run: python tests/test_coach.py   (BURN60_HTML overrides the page path)."""
import json, os
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
HTML = Path(os.environ.get("BURN60_HTML", ROOT / "index.html")).resolve().as_uri()
SHOT = Path(os.environ.get("BURN60_SHOTS", "/tmp/burn60_shots")); SHOT.mkdir(parents=True, exist_ok=True)
CHROME = os.environ.get("CHROME", "/usr/bin/google-chrome")
results = []

def rec(name, ok, detail=""):
    results.append({"name": name, "ok": bool(ok), "detail": str(detail)[:700]})
    print(("PASS" if ok else "FAIL"), name, "-", str(detail)[:200])

def new_page(browser, when=datetime(2026, 11, 23, 12, 0, 0)):
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, timezone_id="Asia/Seoul", locale="ko-KR")
    page = ctx.new_page(); errors = []
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    page.clock.install(time=when)
    page.goto(HTML, wait_until="domcontentloaded"); page.wait_for_timeout(150)
    return ctx, page, errors

# JS prelude: fixtures shared by engine tests. TODAY = Mon 2026-11-23, checkin Sunday (week starts 2026-11-22).
PRE = r"""
const C = window.__burn60.coach;
const TODAY='2026-11-23';
const cfgM = {goal:'loss', sex:'m', age:35, height:175, startWeight:80, targetWeight:75, pal:1.55, workType:'standing', med:'none', medAck:false, startDate:'2026-10-01', totalDays:90};
const place = (o) => Object.assign({name:'home', floorsTotal:10, startFloor:1, topFloor:8, elevator:'yes', handrail:true}, o||{});
const mk = (o) => {
  const c = Object.assign({v:1, startDate:'2026-10-01', places:[place()], activePlace:0,
    joints:{knee:'none',back:false,ankle:false,wrist:false}, fitness:{quick:'3',fTest:null,testDate:null},
    slots:[{name:'evening',min:10}], days:[1,2,3,4,5], equip:[], level:'normal',
    plan:{R:3,N:3,pace:'normal',mode:'stairs',descent:'elevator'}, stairsLocked:false, lockReason:null, lockUntil:null,
    ladderLog:[], lastKcalChange:null, kcalAdj:0, maintenance:false, goalReached:false, checkinDow:0, lastCheckin:null,
    s3:null, reentry:null, needRetest:false, suggestSlot:null, g2Out:0, w4Count:0, lastAvgW:null}, o||{});
  return JSON.parse(JSON.stringify(c));
};
const ses = (d, o) => Object.assign({d, slot:'evening', place:0, plannedRounds:3, doneRounds:3, R:3, pace:'normal', mode:'stairs', talk:5.5, pain:0, redFlag:false, bodyStop:false, missReason:null, userPick:null, secs:0, judged:'ok'}, o||{});
const S = (o) => Object.assign({plannedRounds:3, doneRounds:3, talk:5.5, pain:0, redFlag:false, bodyStop:false, missReason:null, userPick:null}, o||{});
const apply = (coach, sessions, s, today) => C.applySession({coach, cfg:cfgM, sessions}, s, today||TODAY);
const wdata = (vals) => { const d={}; Object.entries(vals).forEach(([k,v])=>{d[k]={weight:v}}); return d; };
const range = (from, n, w) => { const o={}; for(let i=0;i<n;i++){ const dt=new Date(from+'T00:00:00'); dt.setDate(dt.getDate()+i); const k=dt.getFullYear()+'-'+String(dt.getMonth()+1).padStart(2,'0')+'-'+String(dt.getDate()).padStart(2,'0'); o[k]=(typeof w==='function')?w(i):w; } return o; };
const week = (from, rounds, planned) => rounds.map((r,i)=>{ const dt=new Date(from+'T00:00:00'); dt.setDate(dt.getDate()+i); const k=dt.getFullYear()+'-'+String(dt.getMonth()+1).padStart(2,'0')+'-'+String(dt.getDate()).padStart(2,'0'); return r===null?null:ses(k,{plannedRounds:planned||3, doneRounds:r}); }).filter(Boolean);
"""

def ev(page, body):
    return page.evaluate("() => {" + PRE + body + "}")

def engine_tests(page):
    # ---------- §2 initial plan ----------
    r = ev(page, """return {
      base: C.initialPlan(mk({level:'normal'}), cfgM),
      ftest: C.initialPlan(mk({fitness:{quick:'3',fTest:5}}), cfgM),
      span: C.initialPlan(mk({places:[place({startFloor:1, topFloor:3})], fitness:{quick:'6+'}}), cfgM),
      mild: C.initialPlan(mk({joints:{knee:'mild'}, fitness:{quick:'6+'}}), cfgM),
      now: C.initialPlan(mk({joints:{knee:'now'}}), cfgM),
      noplace: C.initialPlan(mk({places:[]}), cfgM),
      noelevMild: C.initialPlan(mk({joints:{knee:'mild'}, places:[place({elevator:'no'})]}), cfgM),
      noelevHard: C.initialPlan(mk({level:'hard', places:[place({elevator:'no'})]}), cfgM),
      hardMed: C.initialPlan(mk({level:'hard'}), Object.assign({}, cfgM, {med:'bp', medAck:false})),
      hardAck: C.initialPlan(mk({level:'hard'}), Object.assign({}, cfgM, {med:'bp', medAck:true})),
      easy: C.initialPlan(mk({level:'easy'}), cfgM),
      hard: C.initialPlan(mk({level:'hard'}), cfgM),
      some: C.initialPlan(mk({places:[place({elevator:'some'})]}), cfgM),
      someMild: C.initialPlan(mk({joints:{knee:'mild'}, places:[place({elevator:'some'})]}), cfgM),
      slot2: C.initialPlan(mk({level:'hard', slots:[{name:'lunch',min:2}]}), cfgM),
    };""")
    b = r["base"]
    rec("plan_R_min_span_fitness", b["R"] == 3 and b["mode"] == "stairs", b)
    rec("plan_fTest_overrides_quick", r["ftest"]["R"] == 5, r["ftest"])
    rec("plan_R_capped_by_span", r["span"]["R"] == 2, r["span"])
    rec("plan_knee_mild_R_le_2_easy", r["mild"]["R"] <= 2 and r["mild"]["pace"] == "easy" and r["mild"]["mode"] == "stairs", r["mild"])
    rec("plan_knee_now_no_stairs", r["now"]["mode"] != "stairs", r["now"])
    rec("plan_no_place_flat", r["noplace"]["mode"] == "flat", r["noplace"])
    rec("plan_no_elevator_knee_mild_flat", r["noelevMild"]["mode"] == "flat", r["noelevMild"])
    rec("plan_no_elevator_N_max3_slow_descent", r["noelevHard"]["N"] <= 3 and r["noelevHard"].get("descent") == "slow", r["noelevHard"])
    rec("plan_hard_blocked_med_no_ack", r["hardMed"]["pace"] != "hard", r["hardMed"])
    rec("plan_hard_ok_med_ack", r["hardAck"]["pace"] == "hard" and r["hardAck"]["N"] == 4, r["hardAck"])
    rec("plan_N_easy2_normal3_hard4", (r["easy"]["N"], b["N"], r["hard"]["N"]) == (2, 3, 4), (r["easy"]["N"], b["N"], r["hard"]["N"]))
    rec("plan_elevator_sometimes_conservative", r["some"]["descent"] == "slow" and r["someMild"]["mode"] == "flat", [r["some"], r["someMild"]])
    rec("plan_N_within_time_budget", r["slot2"]["N"] == 1, r["slot2"])

    # ---------- §3 judge ----------
    j = ev(page, """return {
      n3all: C.judge('normal',3,true,null), n3part: C.judge('normal',3,false,null), n55: C.judge('normal',5.5,true,null),
      n75: C.judge('normal',7.5,true,null), n9: C.judge('normal',9,false,null), nMissHard: C.judge('normal',null,false,'hard'),
      nMissTime: C.judge('normal',null,false,'time'),
      h55: C.judge('hard',5.5,true,null), h75: C.judge('hard',7.5,true,null), h9: C.judge('hard',9,true,null),
      e3: C.judge('easy',3,true,null), e55: C.judge('easy',5.5,true,null), e3part: C.judge('easy',3,false,null)};""")
    rec("judge_normal_below_band_all_done_easy", j["n3all"] == "easy", j)
    rec("judge_below_band_partial_not_easy", j["n3part"] == "ok", j)
    rec("judge_normal_in_band_ok", j["n55"] == "ok", j)
    rec("judge_normal_above_band_hard", j["n75"] == "hard", j)
    rec("judge_talk9_always_hard", j["n9"] == "hard" and j["h9"] == "hard", j)
    rec("judge_none_because_hard_is_hard", j["nMissHard"] == "hard" and j["nMissTime"] != "hard", j)
    rec("judge_hard_band_7_8", j["h55"] == "easy" and j["h75"] == "ok", j)
    rec("judge_easy_band_lowest_button", j["e3"] == "easy" and j["e55"] == "hard" and j["e3part"] == "ok", j)

    # ---------- §4-1 ladder ----------
    l = ev(page, """const c=mk(); return {
      up1: C.ladderUp({R:3,N:3,pace:'normal',mode:'stairs'}, c, cfgM),
      upR: C.ladderUp({R:3,N:6,pace:'normal',mode:'stairs'}, c, cfgM),
      upPaceBlocked: C.ladderUp({R:7,N:6,pace:'normal',mode:'stairs'}, c, cfgM),
      upPaceHard: C.ladderUp({R:7,N:6,pace:'normal',mode:'stairs'}, mk({level:'hard'}), cfgM),
      upEasyToNormal: C.ladderUp({R:7,N:6,pace:'easy',mode:'stairs'}, c, cfgM),
      dn1: C.ladderDown({R:3,N:3,pace:'normal',mode:'stairs'}),
      dnR: C.ladderDown({R:3,N:3,pace:'easy',mode:'stairs'}),
      dnN: C.ladderDown({R:1,N:3,pace:'easy',mode:'stairs'}),
      dnMin: C.ladderDown({R:1,N:1,pace:'easy',mode:'stairs'})};""")
    rec("ladder_up_rounds_first", l["up1"] and l["up1"]["N"] == 4 and l["up1"]["R"] == 3, l["up1"])
    rec("ladder_up_floor_after_6_rounds", l["upR"] and l["upR"]["N"] == 6 and l["upR"]["R"] == 4, l["upR"])
    rec("ladder_up_pace_hard_needs_conditions", l["upPaceBlocked"] is None and l["upPaceHard"] and l["upPaceHard"]["pace"] == "hard", l)
    rec("ladder_up_easy_to_normal", l["upEasyToNormal"] and l["upEasyToNormal"]["pace"] == "normal", l["upEasyToNormal"])
    rec("ladder_down_pace_first", l["dn1"]["pace"] == "easy" and l["dn1"]["R"] == 3 and l["dn1"]["N"] == 3, l["dn1"])
    rec("ladder_down_floors_then_rounds", l["dnR"]["R"] == 2 and l["dnN"]["N"] == 2, l)
    rec("ladder_down_min_1x1", l["dnMin"] is None, l["dnMin"])

    # ---------- weekly cap ----------
    w = ev(page, """return {
      wk: C.weekKey('2026-11-23',0), wkSun: C.weekKey('2026-11-22',0), wkSat: C.weekKey('2026-11-28',0), wkMon: C.weekKey('2026-11-23',1),
      empty: C.canMove(mk(), 1, TODAY),
      afterUp: C.canMove(mk({ladderLog:[{d:'2026-11-22',delta:1,rule:'P1'}]}), 1, TODAY),
      afterUpDown: C.canMove(mk({ladderLog:[{d:'2026-11-22',delta:1,rule:'P1'}]}), -1, TODAY),
      lastWeek: C.canMove(mk({ladderLog:[{d:'2026-11-21',delta:1,rule:'P1'}]}), 1, TODAY)};""")
    rec("weekKey_starts_on_checkin_dow", (w["wk"], w["wkSun"], w["wkSat"], w["wkMon"]) == ("2026-11-22", "2026-11-22", "2026-11-22", "2026-11-23"), w)
    rec("weekly_cap_plus1_once", w["empty"] is True and w["afterUp"] is False, w)
    rec("weekly_cap_net_within_1", w["afterUpDown"] is True, w)
    rec("weekly_cap_resets_next_week", w["lastWeek"] is True, w)

    # ---------- §4-2 session rules + priority ----------
    s = ev(page, """
      const prevEasy=[ses('2026-11-20',{talk:3, judged:'easy'})];
      const prevHard=[ses('2026-11-20',{talk:7.5, judged:'hard'})];
      return {
        s1: apply(mk(), prevEasy, S({bodyStop:true, pain:2, redFlag:true, talk:9})),
        s2rf: apply(mk(), [], S({redFlag:true, pain:0})),
        s2p2: apply(mk(), [], S({pain:2})),
        s3: apply(mk(), [], S({pain:1})),
        s3OverR: apply(mk(), prevHard, S({pain:1, talk:9})),
        s3restore1: apply(mk({plan:{R:2,N:3,pace:'easy',mode:'stairs'}, s3:{prevPace:'normal',prevR:3,ok:0}}), [], S({pain:0})),
        s3restore2: apply(mk({plan:{R:2,N:3,pace:'easy',mode:'stairs'}, s3:{prevPace:'normal',prevR:3,ok:1}}), [], S({pain:0})),
        s3capExempt: apply(mk({ladderLog:[{d:'2026-11-22',delta:-1,rule:'R2'}]}), [], S({pain:1})),
        r1: apply(mk(), [], S({talk:7.5})),
        r2: apply(mk(), prevHard, S({talk:7.5})),
        r2miss: apply(mk(), [ses('2026-11-18',{doneRounds:0, missReason:'hard', talk:null, judged:'hard'})], S({doneRounds:0, talk:null, missReason:'hard'})),
        r2missOld: apply(mk(), [ses('2026-11-15',{doneRounds:0, missReason:'hard', talk:null, judged:'hard'}), ses('2026-11-20')], S({doneRounds:0, talk:null, missReason:'hard'})),
        r2capped: apply(mk({ladderLog:[{d:'2026-11-22',delta:-1,rule:'R2'}]}), prevHard, S({talk:7.5})),
        p1: apply(mk(), prevEasy, S({talk:3})),
        p1one: apply(mk(), [ses('2026-11-20',{talk:5.5, judged:'ok'})], S({talk:3})),
        p1prevPain: apply(mk(), [ses('2026-11-20',{talk:3, judged:'easy', pain:1})], S({talk:3})),
        p1pain: apply(mk(), prevEasy, S({talk:3, pain:1})),
        p1capped: apply(mk({ladderLog:[{d:'2026-11-22',delta:1,rule:'P1'}]}), prevEasy, S({talk:3})),
        p1maint: apply(mk({maintenance:true}), prevEasy, S({talk:3})),
        p1reentry: apply(mk({plan:{R:3,N:2,pace:'easy',mode:'stairs'}, reentry:{until:'2026-11-28', prev:{R:3,N:4,pace:'normal',mode:'stairs'}}}), [], S({plannedRounds:2, doneRounds:2, talk:3})),
        p0: apply(mk(), [], S({talk:5.5})),
        rOverP: apply(mk(), prevEasy, S({talk:9}))
      };""")
    rec("S1_bodystop_top_priority", s["s1"]["rules"][:1] == ["S1"] and s["s1"]["coach"]["stairsLocked"] is True and s["s1"]["coach"]["lockReason"] == "body", s["s1"]["rules"])
    rec("S2_redflag_locks_7d_flat", s["s2rf"]["rules"][:1] == ["S2"] and s["s2rf"]["coach"]["lockReason"] == "knee" and s["s2rf"]["coach"]["lockUntil"] == "2026-11-30" and s["s2rf"]["coach"]["plan"]["mode"] == "flat", s["s2rf"]["coach"].get("lockUntil"))
    rec("S2_pain2_locks", s["s2p2"]["rules"][:1] == ["S2"] and s["s2p2"]["coach"]["stairsLocked"] is True, s["s2p2"]["rules"])
    p = s["s3"]["coach"]["plan"]
    rec("S3_pain1_easy_R_minus1", s["s3"]["rules"][:1] == ["S3"] and p["pace"] == "easy" and p["R"] == 2 and p["N"] == 3, p)
    rec("priority_S_over_R", s["s3OverR"]["rules"][:1] == ["S3"] and "R2" not in s["s3OverR"]["rules"], s["s3OverR"]["rules"])
    rec("S3_restore_needs_2_pain0", s["s3restore1"]["coach"]["plan"]["pace"] == "easy" and s["s3restore2"]["coach"]["plan"]["pace"] == "normal" and s["s3restore2"]["coach"]["plan"]["R"] == 3 and s["s3restore2"]["coach"]["s3"] is None, [s["s3restore1"]["coach"]["plan"], s["s3restore2"]["coach"]["plan"]])
    rec("safety_exempt_from_weekly_cap", s["s3capExempt"]["coach"]["plan"]["R"] == 2, s["s3capExempt"]["coach"]["plan"])
    rec("R1_single_hard_keeps_plan", "R1" in s["r1"]["rules"] and s["r1"]["coach"]["plan"] == {"R":3,"N":3,"pace":"normal","mode":"stairs","descent":"elevator"}, s["r1"])
    rec("R2_two_consecutive_hard_down1", "R2" in s["r2"]["rules"] and s["r2"]["coach"]["plan"]["pace"] == "easy" and s["r2"]["coach"]["plan"]["N"] == 3, s["r2"]["coach"]["plan"])
    rec("R2_two_none_hard_within_7d", "R2" in s["r2miss"]["rules"], s["r2miss"]["rules"])
    rec("R2_none_hard_older_than_7d_not", "R2" not in s["r2missOld"]["rules"], s["r2missOld"]["rules"])
    rec("R2_respects_weekly_cap", "R2" not in s["r2capped"]["rules"] and s["r2capped"]["coach"]["plan"]["pace"] == "normal", s["r2capped"]["rules"])
    rec("P1_two_easy_up1", "P1" in s["p1"]["rules"] and s["p1"]["coach"]["plan"]["N"] == 4, s["p1"]["coach"]["plan"])
    rec("P1_needs_two_sessions", "P1" not in s["p1one"]["rules"] and s["p1one"]["coach"]["plan"]["N"] == 3, s["p1one"]["rules"])
    rec("P1_needs_pain0_both", "P1" not in s["p1prevPain"]["rules"] and "P1" not in s["p1pain"]["rules"], [s["p1prevPain"]["rules"], s["p1pain"]["rules"]])
    rec("P1_once_per_week", "P1" not in s["p1capped"]["rules"] and s["p1capped"]["coach"]["plan"]["N"] == 3, s["p1capped"]["rules"])
    rec("P1_off_in_maintenance", s["p1maint"]["coach"]["plan"]["N"] == 3, s["p1maint"]["rules"])
    rec("P1_reentry_one_session_restores", s["p1reentry"]["coach"]["plan"]["N"] == 4 and s["p1reentry"]["coach"]["reentry"] is None, s["p1reentry"])
    rec("P0_ok_keeps", s["p0"]["coach"]["plan"]["N"] == 3 and "P0" in s["p0"]["rules"], s["p0"]["rules"])
    rec("priority_R_over_P", "P1" not in s["rOverP"]["rules"] and "R1" in s["rOverP"]["rules"], s["rOverP"]["rules"])
    rec("session_record_has_judged", s["p1"]["session"]["judged"] == "easy" and s["p1"]["session"]["d"] == "2026-11-23", s["p1"]["session"])

    # ---------- unlock ----------
    u = ev(page, """
      const lb = mk({stairsLocked:true, lockReason:'body', plan:{R:3,N:5,pace:'normal',mode:'stairs'}});
      const lk = mk({stairsLocked:true, lockReason:'knee', lockUntil:'2026-11-30', plan:{R:3,N:3,pace:'normal',mode:'flat'}});
      return { body: C.unlock(lb,'body',TODAY,true), kneeEarly: C.unlock(lk,'knee','2026-11-29',true),
               kneePain: C.unlock(lk,'knee','2026-11-30',false), kneeOk: C.unlock(lk,'knee','2026-11-30',true) };""")
    rec("S1_unlock_N_50pct_easy", u["body"]["ok"] and u["body"]["coach"]["stairsLocked"] is False and u["body"]["coach"]["plan"]["N"] == 3 and u["body"]["coach"]["plan"]["pace"] == "easy", u["body"]["coach"]["plan"])
    rec("S2_unlock_not_before_7d", u["kneeEarly"]["ok"] is False, u["kneeEarly"].get("ok"))
    rec("S2_unlock_needs_pain0", u["kneePain"]["ok"] is False, u["kneePain"].get("ok"))
    rec("S2_unlock_after_7d_N_50pct", u["kneeOk"]["ok"] and u["kneeOk"]["coach"]["plan"]["N"] == 2 and u["kneeOk"]["coach"]["plan"]["mode"] == "stairs", u["kneeOk"]["coach"]["plan"])

    # ---------- M1/M3/M4 dailyCheck ----------
    m = ev(page, """
      const st = (last, c) => ({coach: c||mk({plan:{R:3,N:4,pace:'normal',mode:'stairs'}}), cfg:cfgM, sessions:[ses(last)]});
      return { g6: C.dailyCheck(st('2026-11-17'), TODAY), g7: C.dailyCheck(st('2026-11-16'), TODAY),
        g13: C.dailyCheck(st('2026-11-10'), TODAY), g14: C.dailyCheck(st('2026-11-09'), TODAY),
        m1: C.dailyCheck({coach:mk(), cfg:cfgM, sessions:[ses('2026-11-19')]}, '2026-11-21'),
        reClear: C.dailyCheck({coach:mk({reentry:{until:'2026-11-20', prev:{R:3,N:4,pace:'normal',mode:'stairs'}}}), cfg:cfgM, sessions:[ses('2026-11-19')]}, TODAY),
        reKeep: C.dailyCheck({coach:mk({reentry:{until:'2026-11-28', prev:{R:3,N:4,pace:'normal',mode:'stairs'}}}), cfg:cfgM, sessions:[ses('2026-11-20')]}, TODAY),
        none9: C.dailyCheck({coach:mk({startDate:'2026-11-01', plan:{R:3,N:2,pace:'easy',mode:'stairs'}}), cfg:cfgM, sessions:[]}, '2026-11-09'),
        none16: C.dailyCheck({coach:mk({startDate:'2026-11-01', plan:{R:3,N:2,pace:'easy',mode:'stairs'}}), cfg:cfgM, sessions:[]}, '2026-11-16'),
        m1rest: C.dailyCheck({coach:mk(), cfg:cfgM, sessions:[ses('2026-11-20')]}, '2026-11-22') };""")
    rec("M3_not_at_6_days", "M3" not in m["g6"]["rules"] and m["g6"]["coach"]["plan"]["N"] == 4, m["g6"]["rules"])
    rec("M3_at_7_days_reentry_half_easy", "M3" in m["g7"]["rules"] and m["g7"]["coach"]["plan"]["N"] == 2 and m["g7"]["coach"]["plan"]["pace"] == "easy" and m["g7"]["coach"]["reentry"]["prev"]["N"] == 4, m["g7"]["coach"]["plan"])
    rec("M3_at_13_days", "M3" in m["g13"]["rules"] and "M4" not in m["g13"]["rules"], m["g13"]["rules"])
    rec("M4_at_14_days_retest", "M4" in m["g14"]["rules"] and m["g14"]["coach"]["needRetest"] is True, m["g14"]["rules"])
    rec("M1_missed_yesterday_no_change", "M1" in m["m1"]["rules"] and m["m1"]["coach"]["plan"]["N"] == 3, m["m1"]["rules"])
    rec("M3_reentry_cleared_after_return_and_expiry", m["reClear"]["coach"]["reentry"] is None and m["reKeep"]["coach"]["reentry"] is not None, [m["reClear"]["coach"]["reentry"], m["reKeep"]["coach"]["reentry"]])
    rec("M3_M4_skip_with_zero_sessions", not any(r in m["none9"]["rules"] + m["none16"]["rules"] for r in ["M3","M4"]) and m["none9"]["coach"]["plan"]["N"] == 2 and m["none16"]["coach"]["reentry"] is None and not m["none16"]["coach"]["needRetest"], [m["none9"]["rules"], m["none16"]["rules"]])
    rec("M1_not_on_rest_day", "M1" not in m["m1rest"]["rules"], m["m1rest"]["rules"])

    # ---------- adherence ----------
    a = ev(page, """return C.adherence(mk(), week('2026-11-16',[3,3,1,0,null,null,null]), '2026-11-16', '2026-11-22');""")
    rec("adherence_rounds_on_planned_days", abs((a["rate"] or 0) - 7/15) < 1e-9 and a["planned"] == 15 and a["done"] == 7, a)

    # ---------- weekly check-in (W/M/G) ----------
    wk = ev(page, r"""
      const wts = (now, ago14, prev) => Object.assign({}, range('2026-11-02',7,ago14), range('2026-11-09',7,prev===undefined?ago14:prev), range('2026-11-16',7,now));
      const run = (o) => C.weeklyCheckin({coach: o.coach||mk(), cfg: o.cfg||cfgM, data: wdata(o.data), sessions: o.sessions||[]}, TODAY);
      const full = week('2026-11-16',[3,3,3,3,3,null,null]);      // 100%
      const r60 = week('2026-11-16',[3,3,3,0,0,null,null]);       // 9/15 = 60%
      const r40 = week('2026-11-16',[3,3,0,0,0,null,null]);       // 6/15 = 40%
      const r70 = week('2026-11-16',[3,3,3,1,1,null,null]);       // 11/15 = 73%
      return {
        m2: run({sessions:r40, data:wts(80,80)}),
        w1_60: run({sessions:r60, data:wts(79.9,80)}),
        w1_60_nostall: run({sessions:r60, data:wts(79.0,80)}),
        skip: run({sessions:full, data:Object.assign(range('2026-11-02',7,80), {'2026-11-16':{weight:80},'2026-11-18':{weight:80},'2026-11-20':{weight:80}})}),
        w2: run({sessions:full, data:wts(79.0,80)}),
        w3: run({sessions:r70, data:wts(79.81,80)}),
        w3edge: run({sessions:r70, data:wts(79.79,80)}),
        w3throttle: run({sessions:r70, data:wts(79.9,80), coach:mk({lastKcalChange:'2026-11-13'})}),
        w3floor: run({sessions:r70, data:wts(79.9,80), coach:mk({kcalAdj:-1000})}),
        w4a: run({sessions:full, data:wts(78.0,80,79.1), coach:mk({w4Count:1})}),
        w4b: run({sessions:full, data:wts(78.0,80,79.0), coach:mk({w4Count:1})}),
        w4first: run({sessions:full, data:wts(78.0,80,79.1), coach:mk({w4Count:0})}),
        w5: run({sessions:full, data:wts(70.1,70), cfg:Object.assign({},cfgM,{goal:'gain', startWeight:70, targetWeight:75})}),
        g1: run({sessions:full, data:wts(74.9,76)}),
        g2a: run({sessions:full, data:wts(76.2,75), coach:mk({maintenance:true, g2Out:0})}),
        g2b: run({sessions:full, data:wts(76.2,75), coach:mk({maintenance:true, g2Out:1})}),
        m2w: run({sessions:r40, data:wts(79.95,80)})
      };""")
    rec("M2_below_50_N_minus1", "M2" in wk["m2"]["rules"] and wk["m2"]["coach"]["plan"]["N"] == 2, wk["m2"]["rules"])
    rec("W1_applies_M2_at_50_70", "W1" in wk["w1_60"]["rules"] and wk["w1_60"]["coach"]["plan"]["N"] == 2 and wk["w1_60"]["coach"]["kcalAdj"] == 0, [wk["w1_60"]["rules"], wk["w1_60"]["coach"]["plan"]])
    rec("W1_no_stall_no_change", "W1" not in wk["w1_60_nostall"]["rules"] and wk["w1_60_nostall"]["coach"]["plan"]["N"] == 3, wk["w1_60_nostall"]["rules"])
    rec("W_skip_under_4_weighins", "W-skip" in wk["skip"]["rules"] and wk["skip"]["coach"]["kcalAdj"] == 0 and not any(x in wk["skip"]["rules"] for x in ["W2","W3"]), wk["skip"]["rules"])
    rec("W2_sets_7day_avg", "W2" in wk["w2"]["rules"] and abs((wk["w2"]["coach"]["lastAvgW"] or 0) - 79.0) < 1e-9, wk["w2"]["coach"].get("lastAvgW"))
    rec("W3_stall_minus100", "W3" in wk["w3"]["rules"] and wk["w3"]["coach"]["kcalAdj"] == -100 and wk["w3"]["coach"]["lastKcalChange"] == "2026-11-23", [wk["w3"]["rules"], wk["w3"]["coach"]["kcalAdj"]])
    rec("W3_threshold_0.2kg", "W3" not in wk["w3edge"]["rules"] and wk["w3edge"]["coach"]["kcalAdj"] == 0, wk["w3edge"]["rules"])
    rec("W3_once_per_2_weeks", wk["w3throttle"]["coach"]["kcalAdj"] == 0, wk["w3throttle"]["rules"])
    rec("W3_at_floor_ladder_up", wk["w3floor"]["coach"]["kcalAdj"] == -1000 and wk["w3floor"]["coach"]["plan"]["N"] == 4, [wk["w3floor"]["rules"], wk["w3floor"]["coach"]["plan"]])
    rec("W4_2wks_over_1kg_plus100", "W4" in wk["w4a"]["rules"] and wk["w4a"]["coach"]["kcalAdj"] == 100, wk["w4a"]["rules"])
    rec("W4_exactly_1kg_not", "W4" not in wk["w4b"]["rules"] and wk["w4b"]["coach"]["w4Count"] == 0, wk["w4b"]["rules"])
    rec("W4_first_week_counts_only", "W4" not in wk["w4first"]["rules"] and wk["w4first"]["coach"]["w4Count"] == 1, wk["w4first"]["coach"].get("w4Count"))
    rec("W5_gain_stall_plus100", "W5" in wk["w5"]["rules"] and wk["w5"]["coach"]["kcalAdj"] == 100, wk["w5"]["rules"])
    rec("G1_goal_reached", "G1" in wk["g1"]["rules"] and wk["g1"]["coach"]["goalReached"] is True, wk["g1"]["rules"])
    rec("G2_needs_2_weeks_out", "G2" not in wk["g2a"]["rules"] and "G2" in wk["g2b"]["rules"] and wk["g2b"]["coach"]["kcalAdj"] == -100, [wk["g2a"]["rules"], wk["g2b"]["rules"]])
    rec("priority_M_over_W_single_step", wk["m2w"]["coach"]["plan"]["N"] == 2 and "W3" not in wk["m2w"]["rules"], [wk["m2w"]["rules"], wk["m2w"]["coach"]["plan"]])
    rec("weekly_note_3_lines_with_rules", len(wk["w3"]["note"]["lines"]) == 3 and wk["w3"]["note"]["rules"] == wk["w3"]["rules"] and wk["w3"]["coach"]["lastCheckin"] == "2026-11-23", wk["w3"]["note"])

    # ---------- kcal target ----------
    k = ev(page, """const c=mk(); const t0=C.kcalTarget(cfgM,c,80); const tf=C.kcalTarget(cfgM,mk({kcalAdj:-1000}),80);
      const tm=C.kcalTarget(cfgM,mk({maintenance:true}),80); const tg=C.kcalTarget(Object.assign({},cfgM,{goal:'gain'}),mk({kcalAdj:1000}),80);
      const tlow=C.kcalTarget(Object.assign({},cfgM,{sex:'f',height:150,age:60,pal:1.2}),mk({kcalAdj:-1000}),45);
      return {t0,tf,tm,tg,tlow};""")
    rec("kcal_loss_floor_tdee_minus500", k["tf"]["target"] == max(1500, round(k["t0"]["tdee"] - 500)) or k["tf"]["target"] == k["tf"]["lo"], k["tf"])
    rec("kcal_range_min_never_below_floor", k["tf"]["min"] >= k["tf"]["lo"] and k["tlow"]["min"] >= 1200, [k["tf"], k["tlow"]])
    rec("kcal_female_floor_1200", k["tlow"]["target"] >= 1200, k["tlow"])
    rec("kcal_maintenance_is_tdee", abs(k["tm"]["target"] - k["t0"]["tdee"]) <= 1, k["tm"])
    rec("kcal_gain_cap_tdee_plus500", k["tg"]["target"] <= k["t0"]["tdee"] + 500 + 1, k["tg"])

def app_tests(browser):
    # migration v2 -> v3 keeps data
    ctx, page, err = new_page(browser)
    page.evaluate("""() => {
      localStorage.setItem('burn60_config', JSON.stringify({schemaVersion:2, goal:'loss', sex:'m', age:35, height:175, startWeight:80, targetWeight:78, totalDays:30, startDate:'2026-11-20', endDate:'2026-12-19', med:'none', pains:['none'], pal:1.55}));
      localStorage.setItem('burn60_data', JSON.stringify({'2026-11-20':{weight:80}}));
      localStorage.setItem('burn60_user', JSON.stringify({xp:5}));
    }""")
    page.reload(wait_until="domcontentloaded"); page.wait_for_timeout(200)
    mg = page.evaluate("() => ({cfg: window.__burn60.getConfig(), coach: JSON.parse(localStorage.getItem('burn60_coach')||'null'), data: JSON.parse(localStorage.getItem('burn60_data')||'null')})")
    rec("v2_data_kept_and_migrated", mg["cfg"] and mg["cfg"]["schemaVersion"] == 3 and mg["data"] and "2026-11-20" in mg["data"] and mg["coach"] is not None, {k: (v if k != "coach" else bool(v)) for k, v in mg.items()})
    rec("migration_no_false_gap_rules", not any(r in (mg["coach"] or {}).get("dailyRules", []) for r in ["M3","M4"]) and not (mg["coach"] or {}).get("needRetest"), (mg["coach"] or {}).get("dailyRules"))
    rec("migration_errors_zero", err == [], err); ctx.close()

    # backup 8 keys + roundtrip + old 4-key backup
    ctx, page, err = new_page(browser)
    bk = page.evaluate("""() => { const b=window.__burn60;
      b.startChallenge({goal:'loss', sex:'m', age:35, height:175, startWeight:80, targetWeight:78, days:30, startDate:'2026-11-23', workType:'standing', preg:'no', ed:'none', med:'none',
        coach:{places:[{name:'home',floorsTotal:10,startFloor:1,topFloor:6,elevator:'yes',handrail:true}], joints:{knee:'none'}, fitness:{quick:'3'}, slots:[{name:'lunch',min:5}], days:[1,2,3,4,5], level:'normal'}});
      localStorage.setItem('burn60_sessions', JSON.stringify([{d:'2026-11-23',plannedRounds:3,doneRounds:2,judged:'ok'}]));
      localStorage.setItem('burn60_notes', JSON.stringify([{wk:'2026-11-22',lines:['a','b','c'],rules:['W2'],changes:[]}]));
      return b.exportData(); }""")
    keys = ["b60lang","burn60_config","burn60_data","burn60_user","burn60_coach","burn60_sessions","burn60_learn","burn60_notes"]
    rec("export_has_8_keys", all(k in bk for k in keys), list(bk.keys()))
    rec("coach_from_start_input", bk["burn60_coach"] and bk["burn60_coach"]["plan"]["mode"] == "stairs" and bk["burn60_coach"]["plan"]["R"] == 3, (bk.get("burn60_coach") or {}).get("plan"))
    rt = page.evaluate("""(bk) => { const b=window.__burn60; b.resetAll(true); const ok=b.importData(bk,true); const now=b.exportData();
      return {ok, same: ['burn60_coach','burn60_sessions','burn60_learn','burn60_notes','burn60_data'].every(k => JSON.stringify(now[k])===JSON.stringify(bk[k]))}; }""", bk)
    rec("import_restores_new_keys", rt["ok"] and rt["same"], rt)
    old = page.evaluate("""(bk) => { const b=window.__burn60; b.resetAll(true); const o={b60lang:bk.b60lang, burn60_config:Object.assign({},bk.burn60_config,{schemaVersion:2}), burn60_data:bk.burn60_data, burn60_user:bk.burn60_user};
      const ok=b.importData(o,true); const now=b.exportData(); return {ok, coach: !!now.burn60_coach, sessions: Array.isArray(now.burn60_sessions), v: now.burn60_config.schemaVersion}; }""", bk)
    rec("old_4key_backup_imports", old["ok"] and old["coach"] and old["sessions"] and old["v"] == 3, old)
    bad = page.evaluate("""(bk) => window.__burn60.importData(Object.assign({}, bk, {burn60_sessions:'x'}), true)""", bk)
    rec("bad_new_key_type_rejected", bad is False, bad)
    page.evaluate("() => window.__burn60.resetAll(true)")
    gone = page.evaluate("() => ['burn60_coach','burn60_sessions','burn60_learn','burn60_notes'].filter(k => localStorage.getItem(k)!==null)")
    rec("reset_clears_new_keys", gone == [], gone)
    rec("backup_errors_zero", err == [], err); ctx.close()

    # no weekly 7->12 increase
    ctx, page, err = new_page(browser)
    ex = page.evaluate("""() => { const b=window.__burn60; const base={goal:'loss', sex:'m', age:35, height:175, startWeight:80, targetWeight:78, days:90, workType:'standing', preg:'no', ed:'none', med:'none'};
      b.startChallenge(Object.assign({},base,{startDate:'2026-11-23'})); const d1=b.getQuests().find(q=>q.id==='ex');
      b.resetAll(true); b.startChallenge(Object.assign({},base,{startDate:'2026-10-01'})); const d50=b.getQuests().find(q=>q.id==='ex');
      return {d1:d1.desc, d50:d50.desc, n:b.getQuests().length}; }""")
    rec("no_weekly_set_increase", ex["d1"] == ex["d50"] and "12" not in ex["d50"].split("×")[-1], ex)
    rec("quest_count_still_14", ex["n"] == 14, ex["n"])
    ts = page.evaluate("() => window.__burn60.getQuests().map(q=>q.time)")
    rec("quests_sorted_by_time", ts == sorted(ts), ts)
    rec("exsets_errors_zero", err == [], err); ctx.close()

def go_onboarding(page, env=True):
    c = lambda tid: page.locator(f'[data-testid="{tid}"]').first.click()
    c("btn-next"); page.wait_for_timeout(100)
    c("opt-sex-m"); page.locator('[data-testid="input-age"]').fill("35"); page.locator('[data-testid="input-height"]').fill("175")
    page.locator('[data-testid="input-sw"]').fill("80"); page.locator('[data-testid="input-tw"]').fill("78")
    c("btn-next"); page.wait_for_timeout(100)
    c("ob-knee-none"); c("opt-med-none"); c("btn-next"); page.wait_for_timeout(150)
    c("opt-preg-na"); c("opt-ed-none"); c("btn-next"); page.wait_for_timeout(150)
    if env:
        c("ob-place-home")
        page.locator('[data-testid="ob-floors"]').fill("10"); page.locator('[data-testid="ob-start-floor"]').fill("1"); page.locator('[data-testid="ob-top-floor"]').fill("6")
        c("ob-elev-yes"); c("ob-quick-3"); c("ob-slot-lunch"); c("ob-min-5"); c("ob-level-normal")

def smoke(browser):
    ctx, page, err = new_page(browser)
    c = lambda tid: page.locator(f'[data-testid="{tid}"]').first.click()
    go_onboarding(page)
    c("btn-later"); page.wait_for_timeout(250)
    coach = page.evaluate("() => JSON.parse(localStorage.getItem('burn60_coach')||'null')")
    rec("smoke_onboarding_started", page.evaluate("() => window.__burn60.getConfig()") is not None and coach and coach["plan"]["mode"] == "stairs" and coach["plan"]["R"] == 3 and coach["plan"]["N"] == 2, (coach or {}).get("plan"))
    hero = page.locator('[data-testid="hero-count"]')
    rec("smoke_today_hero_0_of_2", hero.count() > 0 and hero.first.inner_text().replace(" ", "") == "0/2", hero.first.inner_text() if hero.count() else "missing")
    btn = page.locator('[data-testid="btn-primary"]')
    rec("smoke_primary_round", btn.count() > 0 and btn.first.get_attribute("data-state") == "round" and "이 라운드 완료" in btn.first.inner_text(), btn.first.inner_text() if btn.count() else "missing")
    exq = page.evaluate("() => window.__burn60.getQuests().find(q=>q.id==='ex')")
    rec("smoke_ex_quest_time_from_slot", exq["time"] == "12:30", exq)
    rec("smoke_stop_signs_present", page.locator('[data-testid="stop-signs"]').count() > 0 and "119" in page.locator('[data-testid="stop-signs"]').first.text_content() and "120" in page.locator('[data-testid="stop-signs"]').first.text_content(), "ok")
    # round 1: full 3-tap
    c("btn-primary"); page.wait_for_timeout(150)
    rec("smoke_check_sheet_open", page.locator('[data-testid="check-sheet"]').count() > 0 and page.locator('[data-testid="talk-3"]').count() > 0, "sheet")
    c("talk-3"); page.wait_for_timeout(80); c("pain-0"); page.wait_for_timeout(80)
    rec("smoke_step3_visible", page.locator('[data-testid="done-all"]').count() > 0, "step3")
    c("done-all"); page.wait_for_timeout(200)
    sess = page.evaluate("() => JSON.parse(localStorage.getItem('burn60_sessions')||'[]')")
    rec("smoke_round1_saved", len(sess) == 1 and sess[0]["doneRounds"] == 1 and sess[0]["plannedRounds"] == 2 and page.locator('[data-testid="check-sheet"]').count() == 0, sess)
    rec("smoke_hero_1_of_2", page.locator('[data-testid="hero-count"]').first.inner_text().replace(" ", "") == "1/2", page.locator('[data-testid="hero-count"]').first.inner_text())
    # round 2: later -> resume
    c("btn-primary"); page.wait_for_timeout(100); c("talk-5.5"); page.wait_for_timeout(80)
    c("btn-later-session"); page.wait_for_timeout(150)
    btn = page.locator('[data-testid="btn-primary"]').first
    line = page.locator('[data-testid="today-line"]').first.inner_text()
    rec("smoke_resume_state", btn.get_attribute("data-state") == "resume" and "이어서" in btn.inner_text() and "세션 기록을 이어서 남겨 주세요." in line, [btn.inner_text(), line])
    page.reload(wait_until="domcontentloaded"); page.wait_for_timeout(200)
    rec("smoke_draft_survives_reload", page.locator('[data-testid="btn-primary"]').first.get_attribute("data-state") == "resume", "resume after reload")
    c("btn-primary"); page.wait_for_timeout(120)
    rec("smoke_resume_opens_saved_step", page.locator('[data-testid="pain-0"]').count() > 0 and page.locator('[data-testid="talk-3"]').count() == 0, "step 2")
    c("pain-0"); page.wait_for_timeout(80); c("done-all"); page.wait_for_timeout(200)
    sess = page.evaluate("() => JSON.parse(localStorage.getItem('burn60_sessions')||'[]')")
    learn = page.evaluate("() => JSON.parse(localStorage.getItem('burn60_learn')||'null')")
    ck = page.evaluate("() => JSON.parse(localStorage.getItem('burn60_coach'))")
    rec("smoke_two_rounds_one_session", len(sess) == 1 and sess[0]["doneRounds"] == 2 and sess[0]["talk"] == 5.5 and sess[0]["judged"] == "ok", sess)
    rec("smoke_learn_counted_once_per_day", learn and learn["slots"].get("lunch", {}).get("offered") == 2 and learn["slots"]["lunch"]["done"] == 2, learn)
    rec("smoke_no_ladder_stacking", len(ck.get("ladderLog") or []) == 0 and ck["plan"]["N"] == 2 and ck.get("draft") is None, [ck.get("ladderLog"), ck["plan"]])
    rec("smoke_ex_quest_autochecked", page.evaluate("() => { const d=JSON.parse(localStorage.getItem('burn60_data')); return !!(d['2026-11-23'] && d['2026-11-23'].quests && d['2026-11-23'].quests.ex); }"), "ex")
    btn = page.locator('[data-testid="btn-primary"]').first
    rec("smoke_primary_disabled_when_done", btn.is_disabled(), btn.inner_text())
    # weight row: starts empty, save disabled until typed
    c("row-weight-add"); page.wait_for_timeout(100)
    wi = page.locator('[data-testid="input-weight"]').first
    sv = page.locator('[data-testid="btn-weight-save"]').first
    rec("smoke_weight_input_empty", wi.input_value() == "", wi.input_value())
    rec("smoke_weight_save_disabled_empty", sv.is_disabled(), "disabled")
    wi.fill("79.5"); page.wait_for_timeout(80)
    rec("smoke_weight_save_enabled_typed", not page.locator('[data-testid="btn-weight-save"]').first.is_disabled(), "enabled")
    page.locator('[data-testid="btn-weight-save"]').first.click(); page.wait_for_timeout(150)
    rec("smoke_weight_saved", page.evaluate("() => JSON.parse(localStorage.getItem('burn60_data'))['2026-11-23'].weight") == 79.5, "79.5")
    c("row-water-add"); page.wait_for_timeout(100)
    rec("smoke_water_saved", page.evaluate("() => JSON.parse(localStorage.getItem('burn60_data'))['2026-11-23'].water") == 1, "1")
    # zh
    page.evaluate("() => window.__burn60.setLang('zh')"); page.wait_for_timeout(120)
    rec("smoke_zh_today", "轮" in page.locator('[data-testid="today-hero"]').first.inner_text(), page.locator('[data-testid="today-hero"]').first.inner_text()[:80])
    page.evaluate("() => window.__burn60.setLang('ko')"); page.wait_for_timeout(80)
    # tabs
    rec("smoke_tabs_3", all(page.locator(f'[data-testid="{t}"]').count() > 0 for t in ("nav-today", "nav-log", "nav-settings")), "tabs")
    c("nav-log"); page.wait_for_timeout(100)
    rec("smoke_log_notes_list", page.locator('[data-testid="notes-list"]').count() > 0, "notes-list")
    c("nav-settings"); page.wait_for_timeout(100)
    rec("smoke_settings_backup_buttons", page.locator('[data-testid="btn-export"]').count() > 0 and page.locator('[data-testid="btn-coach-settings"]').count() > 0, "settings")
    c("theme-dark"); page.wait_for_timeout(100)
    rec("smoke_theme_dark", page.evaluate("() => document.documentElement.getAttribute('data-theme')") == "dark" and page.evaluate("() => localStorage.getItem('b60theme')") == "dark", "dark")
    c("theme-light"); page.wait_for_timeout(80)
    c("nav-today"); page.wait_for_timeout(100)
    c("btn-stop"); page.wait_for_timeout(150)
    s1 = page.locator('[data-testid="s1-screen"]')
    rec("smoke_stop_screen_119_120", s1.count() > 0 and "119" in s1.first.inner_text() and "120" in s1.first.inner_text(), s1.first.inner_text()[:160] if s1.count() else "missing")
    rec("smoke_errors_day1", err == [], err)
    ctx.close()

    # weekly check-in screen
    ctx, page, err = new_page(browser)
    page.evaluate("""() => { const b=window.__burn60;
      b.startChallenge({goal:'loss', sex:'m', age:35, height:175, startWeight:80, targetWeight:75, days:60, startDate:'2026-11-16', workType:'standing', preg:'no', ed:'none', med:'none'}); }""")
    page.clock.set_system_time(datetime(2026, 11, 30, 9, 0, 0))
    page.reload(wait_until="domcontentloaded"); page.wait_for_timeout(300)
    note = page.locator('[data-testid="weekly-note"]')
    notes = page.evaluate("() => JSON.parse(localStorage.getItem('burn60_notes')||'[]')")
    rec("smoke_weekly_checkin_note", note.count() > 0 and len(notes) == 1 and len(notes[0]["lines"]) == 3, notes)
    rec("smoke_weekly_ok_button", page.locator('[data-testid="btn-weekly-ok"]').count() > 0, "ok btn")
    page.locator('[data-testid="btn-weekly-ok"]').first.click(); page.wait_for_timeout(150)
    rec("smoke_weekly_ack_returns_today", page.locator('[data-testid="weekly-note"]').count() == 0 and page.locator('[data-testid="today-hero"]').count() > 0, "today")
    page.reload(wait_until="domcontentloaded"); page.wait_for_timeout(200)
    notes2 = page.evaluate("() => JSON.parse(localStorage.getItem('burn60_notes')||'[]')")
    rec("smoke_checkin_once_per_week", len(notes2) == 1, len(notes2))
    rec("smoke_errors_weekly", err == [], err)
    ctx.close()

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, args=["--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"])
        for fn in (lambda: engine_tests(new_page(browser)[1]), lambda: app_tests(browser), lambda: smoke(browser)):
            try:
                fn()
            except Exception as e:
                import traceback; rec("exception", False, "\n".join(l for l in traceback.format_exc().splitlines() if "site-packages" not in l)[-1500:])
        browser.close()
    passed = sum(r["ok"] for r in results); failed = [r for r in results if not r["ok"]]
    print(f"\nSUMMARY {passed}/{len(results)} passed, {len(failed)} failed")
    for r in failed: print("FAIL", r["name"], r["detail"][:300])
    Path(os.environ.get("BURN60_RESULTS_COACH", "/tmp/burn60_results_coach.json")).write_text(json.dumps({"passed": passed, "total": len(results), "results": results}, ensure_ascii=False, indent=2))
    return 0 if not failed else 1

if __name__ == "__main__":
    raise SystemExit(main())
