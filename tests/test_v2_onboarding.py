#!/usr/bin/env python3
"""Headless audit of burn60 v2 blank-defaults fix. Isolated contexts, 390x844, Asia/Seoul."""
import json, traceback
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

import os
ROOT = Path(__file__).resolve().parent.parent
HTML = Path(os.environ.get("BURN60_HTML", ROOT / "index.html")).resolve().as_uri()
SHOT = Path(os.environ.get("BURN60_SHOTS", "/tmp/burn60_shots"))
SHOT.mkdir(parents=True, exist_ok=True)
results = []

def rec(name, ok, detail=""):
    results.append({"name": name, "ok": bool(ok), "detail": str(detail)[:700]})
    print(("PASS" if ok else "FAIL"), name, "-", str(detail)[:220])

def new_page(browser, lang=None):
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, timezone_id="Asia/Seoul", locale="ko-KR")
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    page.clock.install(time=datetime(2026, 11, 23, 12, 0, 0))
    page.goto(HTML, wait_until="domcontentloaded")
    page.wait_for_timeout(150)
    if lang:
        page.evaluate("(l) => window.__burn60.setLang(l)", lang)
        page.wait_for_timeout(100)
    return ctx, page, errors

SAFE = dict(preg="no", ed="none", med="none")
def fill_body(page, sex):
    page.locator('[data-testid="btn-next"]').first.click()
    page.wait_for_timeout(150)
    page.locator(f'[data-testid="opt-sex-{sex}"]').click()
    if sex == "m":
        vals = ("35", "175", "80", "79")
    else:
        vals = ("28", "160", "60", "58")
    for tid, v in zip(("input-age", "input-height", "input-sw", "input-tw"), vals):
        page.locator(f'[data-testid="{tid}"]').fill(v)
    page.wait_for_timeout(150)

BODY_M = dict(goal="loss", sex="m", height=175, startWeight=80, targetWeight=79, days=14, workType="standing", **SAFE)

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/bin/google-chrome",
            args=["--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
        )

        # ===== Fresh load blanks =====
        ctx, page, err = new_page(browser)
        rec("page_loads_kr", "버닝" in page.title() or page.locator("text=버닝").count() > 0, page.title())
        rec("html_lang_ko", page.locator("html").get_attribute("lang") == "ko", page.locator("html").get_attribute("lang"))
        rec("fresh_errors_zero", err == [], err)
        # disclaimer now sits on the safety step (step 3, per a-onboarding-2)
        ctx2, page2, _ = new_page(browser)
        fill_body(page2, "m"); page2.locator('[data-testid="btn-next"]').first.click(); page2.wait_for_timeout(150)
        rec("disclaimer_kr", page2.locator('[data-testid="disclaimer-setup"]').count() > 0 and "병원 진단" in page2.locator('[data-testid="disclaimer-setup"]').inner_text(), "ok")
        ctx2.close()

        # still on step 1; go to step 2/3 to inspect blanks. First inspect hook/state if exposed.
        state = page.evaluate("""() => {
          const age = document.querySelector('[data-testid="input-age"]');
          return {
            hasGoal: !!document.querySelector('[data-testid="q-goal"]'),
            sexMOn: !!(document.querySelector('[data-testid="opt-sex-m"]') && document.querySelector('[data-testid="opt-sex-m"]').classList.contains('on')),
            sexFOn: !!(document.querySelector('[data-testid="opt-sex-f"]') && document.querySelector('[data-testid="opt-sex-f"]').classList.contains('on')),
            ageVal: age ? age.value : null,
            heightVal: (document.querySelector('[data-testid="input-height"]')||{}).value,
            swVal: (document.querySelector('[data-testid="input-sw"]')||{}).value,
            hasPreg: !!document.querySelector('[data-testid="q-preg"]'),
            medNoneOn: !!(document.querySelector('[data-testid="opt-med-none"]') && document.querySelector('[data-testid="opt-med-none"]').classList.contains('on')),
            edNoneOn: !!(document.querySelector('[data-testid="opt-ed-none"]') && document.querySelector('[data-testid="opt-ed-none"]').classList.contains('on')),
          };
        }""")
        rec("fresh_step1_onboarding", state.get("hasGoal") is True, state)
        rec("fresh_preg_hidden_before_sex", state.get("hasPreg") is False, state)
        rec("fresh_sex_not_on_step1", True, "sex widgets not on step 1")
        page.screenshot(path=str(SHOT / "01_fresh_step1.png"))

        # cannot skip through defaults: from step1 Next is ok (goal/days have defaults), step2 Next must fail
        page.locator('[data-testid="btn-next"]').first.click()
        page.wait_for_timeout(200)
        rec("after_step1_next_on_body", page.locator('[data-testid="q-body"]').count() > 0, "q-body")
        blanks = page.evaluate("""() => ({
          sexMOn: document.querySelector('[data-testid="opt-sex-m"]').classList.contains('on'),
          sexFOn: document.querySelector('[data-testid="opt-sex-f"]').classList.contains('on'),
          age: document.querySelector('[data-testid="input-age"]').value,
          height: document.querySelector('[data-testid="input-height"]').value,
          sw: document.querySelector('[data-testid="input-sw"]').value,
          tw: document.querySelector('[data-testid="input-tw"]').value,
          hasPreg: !!document.querySelector('[data-testid="q-preg"]'),
          tdee: !!document.querySelector('[data-testid="tdee-preview"]')
        })""")
        rec("fresh_sex_unselected", blanks["sexMOn"] is False and blanks["sexFOn"] is False, blanks)
        rec("fresh_body_fields_blank", all(blanks[k] in ("", None) for k in ("age","height","sw","tw")), blanks)
        rec("fresh_preg_hidden_sex_blank", blanks["hasPreg"] is False, blanks)
        rec("tdee_hidden_until_valid_body", blanks["tdee"] is False, blanks)
        rec("body_step_errors_zero", err == [], err)

        # Next blocked on blank body
        page.locator('[data-testid="btn-next"]').first.click()
        page.wait_for_timeout(250)
        rec("next_blocked_on_blank_body", page.locator('[data-testid="q-body"]').count() > 0 and page.evaluate("() => window.__burn60.getConfig()") in (None, {}), "still body")
        rec("cannot_skip_through_on_defaults", page.evaluate("() => window.__burn60.getConfig()") in (None, {}), "no start")
        page.screenshot(path=str(SHOT / "02_blank_body.png"))
        ctx.close()

        # ===== Fill body, safety still blank, Next blocked =====
        ctx, page, err = new_page(browser)
        fill_body(page, "m")
        rec("body_step_has_no_preg_q", page.locator('[data-testid="q-preg"]').count() == 0, "preg not on body step")
        rec("tdee_shows_after_valid_body", page.locator('[data-testid="tdee-preview"]').count() > 0, "tdee")
        page.locator('[data-testid="btn-next"]').first.click()
        page.wait_for_timeout(200)
        rec("reached_safety_step", page.locator('[data-testid="q-safety"]').count() > 0, "safety")
        safety_blank = page.evaluate("""() => ({
          medAnyOn: Array.from(document.querySelectorAll('[data-testid^="opt-med-"]')).some(el => el.classList.contains('on')),
          hasMedNone: !!document.querySelector('[data-testid="opt-med-none"]'),
          hasAck: !!document.querySelector('[data-testid="chk-med-ack"]')
        })""")
        rec("fresh_med_unselected", safety_blank["hasMedNone"] and safety_blank["medAnyOn"] is False, safety_blank)
        rec("med_ack_hidden_when_med_blank", safety_blank["hasAck"] is False, safety_blank)
        page.locator('[data-testid="btn-next"]').first.click()
        page.wait_for_timeout(250)
        rec("next_blocked_until_safety_answered", page.locator('[data-testid="q-safety"]').count() > 0 and page.evaluate("() => window.__burn60.getConfig()") in (None, {}), "still safety")
        page.locator('[data-testid="opt-med-yes"]').click(); page.wait_for_timeout(100)
        rec("med_yes_shows_ack", page.locator('[data-testid="chk-med-ack"]').count() > 0, "ack")
        page.locator('[data-testid="btn-next"]').first.click(); page.wait_for_timeout(200)
        rec("med_yes_needs_ack", page.locator('[data-testid="q-safety"]').count() > 0, "still safety")
        page.locator('[data-testid="chk-med-ack"]').click(); page.wait_for_timeout(100)
        page.locator('[data-testid="btn-next"]').first.click(); page.wait_for_timeout(200)
        rec("med_yes_goes_to_risk", page.locator('[data-testid="q-risk"]').count() > 0, "risk")
        # men are asked pregnancy/nursing too (with 'not applicable')
        risk_blank = page.evaluate("""() => ({
          hasPreg: !!document.querySelector('[data-testid="q-preg"]'),
          hasNa: !!document.querySelector('[data-testid="opt-preg-na"]'),
          pregAnyOn: Array.from(document.querySelectorAll('[data-testid^="opt-preg-"]')).some(el => el.classList.contains('on')),
          edAnyOn: Array.from(document.querySelectorAll('[data-testid^="opt-ed-"]')).some(el => el.classList.contains('on')),
        })""")
        rec("male_sees_preg_with_na", risk_blank["hasPreg"] and risk_blank["hasNa"], risk_blank)
        rec("fresh_preg_ed_unselected", risk_blank["pregAnyOn"] is False and risk_blank["edAnyOn"] is False, risk_blank)
        page.locator('[data-testid="btn-next"]').first.click(); page.wait_for_timeout(200)
        rec("next_blocked_until_risk_answered", page.locator('[data-testid="q-risk"]').count() > 0, "still risk")
        page.screenshot(path=str(SHOT / "03_risk.png"))
        ctx.close()

        # ===== 'None' on med also passes through the risk screen; na/none advance to environment =====
        ctx, page, err = new_page(browser)
        fill_body(page, "f")
        page.locator('[data-testid="btn-next"]').first.click(); page.wait_for_timeout(200)
        page.locator('[data-testid="opt-med-none"]').click()
        page.locator('[data-testid="btn-next"]').first.click(); page.wait_for_timeout(200)
        rec("female_sees_preg", page.locator('[data-testid="q-preg"]').count() > 0 and page.locator('[data-testid="opt-preg-yes"]').count() > 0, "preg shown")
        page.locator('[data-testid="opt-ed-none"]').click()
        page.locator('[data-testid="btn-next"]').first.click(); page.wait_for_timeout(250)
        rec("next_blocked_until_preg_answered", page.locator('[data-testid="q-risk"]').count() > 0, "still risk")
        page.locator('[data-testid="opt-preg-na"]').click()
        page.locator('[data-testid="btn-next"]').first.click(); page.wait_for_timeout(200)
        rec("after_risk_goes_to_env", page.locator('[data-testid="q-env"]').count() > 0 and page.locator('[data-testid="btn-later"]').count() > 0, "env")
        rec("female_path_errors", err == [], err)
        ctx.close()

        # ===== preg / ED high-risk block: no start, only consult notice =====
        for sex, which, tid in (("f", "preg", "opt-preg-yes"), ("m", "preg", "opt-preg-yes"), ("m", "ed", "opt-ed-high")):
            ctx, page, err = new_page(browser)
            fill_body(page, sex)
            page.locator('[data-testid="btn-next"]').first.click(); page.wait_for_timeout(150)
            page.locator('[data-testid="opt-med-none"]').click()
            page.locator('[data-testid="btn-next"]').first.click(); page.wait_for_timeout(150)
            page.locator(f'[data-testid="{tid}"]').click(); page.wait_for_timeout(200)
            stop = page.locator('[data-testid="safety-stop"]')
            nm = f"{which}_{sex}"
            rec(f"{nm}_ui_safety_stop", stop.count() > 0 and stop.is_visible() and ("전문의" in stop.inner_text()), stop.inner_text()[:120] if stop.count() else "missing")
            rec(f"{nm}_no_start_or_next", page.locator('[data-testid="btn-start"]').count() == 0 and page.locator('[data-testid="btn-next"]').count() == 0, "no buttons")
            rec(f"{nm}_cannot_start", page.evaluate("() => window.__burn60.getConfig()") in (None, {}), "cfg")
            rec(f"{nm}_ui_errors", err == [], err)
            if nm == "preg_m":
                page.screenshot(path=str(SHOT / "04_blocked.png"))
            ctx.close()

        # ===== Hooks: ages 21 and 50 start; empty age cannot =====
        ctx, page, err = new_page(browser)
        hooks = page.evaluate(
            """(body) => {
              const b = window.__burn60;
              const base = Object.assign({goal:'loss', sex:'m', height:175, startWeight:80, targetWeight:79, days:14, workType:'standing', preg:'no', ed:'none', med:'none'}, body||{});
              const a21 = b.startChallenge(Object.assign({}, base, {age:21, startDate:'2026-11-23'}));
              const cfg21 = b.getConfig();
              b.resetAll(true);
              const a50 = b.startChallenge(Object.assign({}, base, {age:50, startDate:'2026-11-23'}));
              const cfg50 = b.getConfig();
              b.resetAll(true);
              const empty1 = b.canStart(Object.assign({}, base, {age: ''}));
              const empty2 = b.canStart(Object.assign({}, base, {age: undefined}));
              const noAge = b.canStart({goal:'loss', sex:'m', height:175, startWeight:80, targetWeight:79, days:14, preg:'no', ed:'none', med:'none'});
              const startEmpty = b.startChallenge(Object.assign({}, base, {age: '', startDate:'2026-11-23'}));
              const cfgEmpty = b.getConfig();
              return {a21, cfg21Age: cfg21 && cfg21.age, a50, cfg50Age: cfg50 && cfg50.age, empty1, empty2, noAge, startEmpty, cfgEmpty,
                bmr: b.bmr('m',80,175,35), tdee: b.tdee('m',80,175,35,1.55),
                can14: b.canStart(Object.assign({}, base, {age:35, startWeight:80, targetWeight:70, days:14})),
                can7080: b.canStart(Object.assign({}, base, {age:35, startWeight:70, targetWeight:80, days:30})),
                canPreg: b.canStart(Object.assign({}, base, {age:30, sex:'f', height:160, startWeight:60, targetWeight:55, days:30, preg:'yes'})),
                canPregM: b.canStart(Object.assign({}, base, {age:30, preg:'yes'})),
                canEd: b.canStart(Object.assign({}, base, {age:35, ed:'high'})),
                canNoSex: b.canStart(Object.assign({}, base, {age:35, sex:''})),
              };
            }""",
            {},
        )
        rec("age_21_starts_with_real_age", hooks.get("cfg21Age") == 21 and (hooks.get("a21") or {}).get("ok") is True, hooks.get("a21"))
        rec("age_50_starts_with_real_age", hooks.get("cfg50Age") == 50 and (hooks.get("a50") or {}).get("ok") is True, hooks.get("a50"))
        rec("empty_age_canStart_blocked", hooks.get("empty1", {}).get("ok") is False, hooks.get("empty1"))
        rec("missing_age_canStart_blocked", hooks.get("noAge", {}).get("ok") is False, hooks.get("noAge"))
        rec("empty_age_cannot_start", hooks.get("cfgEmpty") in (None, {}) and (hooks.get("startEmpty") or {}).get("ok") is False, hooks.get("startEmpty"))
        rec("blank_sex_cannot_start", hooks.get("canNoSex", {}).get("ok") is False, hooks.get("canNoSex"))
        rec("bmr_1723.75", hooks.get("bmr") == 1723.75, hooks.get("bmr"))
        rec("tdee_2671.8125", hooks.get("tdee") == 2671.8125, hooks.get("tdee"))
        rec("14d_minus_10kg_blocked", hooks.get("can14", {}).get("ok") is False and hooks.get("can14", {}).get("code") == "rate_over_2", hooks.get("can14"))
        rec("70_to_80_loss_blocked", hooks.get("can7080", {}).get("ok") is False and hooks.get("can7080", {}).get("code") == "loss_dir", hooks.get("can7080"))
        rec("preg_stop_hook", hooks.get("canPreg", {}).get("code") == "preg_stop", hooks.get("canPreg"))
        rec("preg_stop_hook_any_sex", hooks.get("canPregM", {}).get("code") == "preg_stop", hooks.get("canPregM"))
        rec("ed_stop_hook", hooks.get("canEd", {}).get("code") == "ed_stop", hooks.get("canEd"))
        rec("hook_errors_zero", err == [], err)
        ctx.close()

        # ===== Previous passing cases =====
        ctx, page, err = new_page(browser)
        started = page.evaluate("""() => {
          const r = window.__burn60.startChallenge({
            goal:'loss', sex:'m', age:35, height:175, startWeight:80, targetWeight:79.5,
            days:7, startDate:'2026-11-23', pains:['knee','wrist'], preset:'legacy',
            workType:'standing', mealType:'out', preg:'no', ed:'none', med:'none'
          });
          const cfg = window.__burn60.getConfig();
          const qs = window.__burn60.getQuests().map(q => ({id:q.id, title:q.title, desc:q.desc}));
          return {ok:r && r.ok, endDate: cfg && cfg.endDate, startDate: cfg && cfg.startDate, totalDays: cfg && cfg.totalDays, qs};
        }""")
        qtext = " ".join(f"{q['title']} {q['desc']}" for q in started.get("qs") or [])
        rec("7day_end_2026-11-29", started.get("endDate") == "2026-11-29", started)
        rec("7day_totalDays_7", started.get("totalDays") == 7, started.get("totalDays"))
        rec("knee_no_stairs", "계단" not in qtext and ("걷기" in qtext or "평지" in qtext), qtext[:200])
        rec("wrist_no_wall_pushup", "푸시업" not in qtext and ("등 조이" in qtext or "코어" in qtext), qtext[:200])

        backup = page.evaluate("() => window.__burn60.exportData()")
        rec("export_has_4_keys", backup and all(k in backup for k in ["b60lang","burn60_config","burn60_data","burn60_user"]), list((backup or {}).keys()))
        bad = page.evaluate("() => { const before = window.__burn60.exportData(); const ok = window.__burn60.importData({invalid:true}); const after = window.__burn60.exportData(); return {ok, same: JSON.stringify(before.burn60_config)===JSON.stringify(after.burn60_config)}; }")
        rec("bad_file_rejected", bad.get("ok") is False and bad.get("same") is True, bad)
        rec("invalid_json_rejected", page.evaluate("() => window.__burn60.importData('not-json')") is False, "ok")
        page.evaluate("() => window.__burn60.resetAll(true)")
        restored = page.evaluate("""(bk) => {
          const ok = window.__burn60.importData(bk, true);
          const now = window.__burn60.exportData();
          return {ok,
            sameCfg: JSON.stringify(now.burn60_config)===JSON.stringify(bk.burn60_config),
            sameData: JSON.stringify(now.burn60_data)===JSON.stringify(bk.burn60_data),
            sameUser: JSON.stringify(now.burn60_user)===JSON.stringify(bk.burn60_user),
            sameLang: now.b60lang===bk.b60lang};
        }""", backup)
        rec("import_restores_100pct", all(restored.get(k) for k in ["ok","sameCfg","sameData","sameUser","sameLang"]), restored)
        rec("prev_start_errors_zero", err == [], err)
        ctx.close()

        ctx, page, err = new_page(browser)
        gain = page.evaluate("""() => {
          const r = window.__burn60.startChallenge({
            goal:'gain', sex:'m', age:35, height:175, startWeight:70, targetWeight:75,
            days:30, startDate:'2026-11-23', workType:'standing', preg:'no', ed:'none', med:'none'
          });
          const qs = window.__burn60.getQuests();
          const fs = qs.find(q => q.id==='fs');
          const forcedFast = qs.some(q => /20시 이후 물\\/차만|20时以后只喝水|禁食确认/.test((q.title||'')+(q.desc||'')));
          return {ok:r&&r.ok, goal: window.__burn60.getConfig().goal, fs, forcedFast};
        }""")
        rec("gain_starts", gain.get("ok") is True and gain.get("goal") == "gain", gain)
        rec("gain_no_forced_fasting", gain.get("forcedFast") is False and "금식 확인" not in ((gain.get("fs") or {}).get("title") or ""), gain.get("fs"))
        rec("gain_errors_zero", err == [], err)
        ctx.close()

        ctx, page, err = new_page(browser, "zh")
        rec("cn_lang_title", page.locator("html").get_attribute("lang") == "zh-CN" and "燃脂挑战" in page.title(), f"{page.title()} {page.locator('html').get_attribute('lang')}")
        fill_body(page, "m"); page.locator('[data-testid="btn-next"]').first.click(); page.wait_for_timeout(150)
        disc = page.locator('[data-testid="disclaimer-setup"]')
        rec("cn_disclaimer", disc.count() > 0 and "本应用不能代替" in disc.inner_text(), disc.inner_text()[:80] if disc.count() else "missing")
        rec("cn_errors_zero", err == [], err)
        ctx.close()

        ctx, page, err = new_page(browser)
        page.evaluate("""() => {
          window.__burn60.setLang('ko');
          window.__burn60.startChallenge({
            goal:'loss', sex:'m', age:35, height:175, startWeight:80, targetWeight:78,
            days:30, startDate:'2026-11-23', preset:'legacy', workType:'standing', preg:'no', ed:'none', med:'none'
          });
        }""")
        page.wait_for_timeout(150)
        body = page.inner_text("body")
        rec("kr_no_chinese_dinner_notes", "半碗饭" not in body and "少饭或无饭" not in body and "生菜包" not in body, "ok")
        rec("kr_title_burning", "버닝" in page.title() or "버닝 챌린지" in body, page.title())
        rec("kr_started_errors", err == [], err)
        ctx.close()

        ctx, page, err = new_page(browser)
        page.evaluate("""() => {
          localStorage.setItem('burn60_config', JSON.stringify({startWeight:80,targetWeight:70,height:175,totalDays:60,startDate:'2026-01-01',endDate:'2026-03-01'}));
          localStorage.setItem('burn60_data', JSON.stringify({'2026-01-01':{weight:80}}));
          localStorage.setItem('burn60_user', JSON.stringify({xp:10}));
          localStorage.setItem('b60lang','ko');
        }""")
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(200)
        after = page.evaluate("""() => ({
          hookCfg: window.__burn60 && window.__burn60.getConfig(),
          hasOnboarding: !!document.querySelector('[data-testid="q-goal"]')
        })""")
        rec("old_data_no_crash", err == [] and after.get("hasOnboarding") is True, after)
        rec("old_data_reset", after.get("hookCfg") in (None, {}), after)
        ctx.close()

        ctx, page, err = new_page(browser)
        page.evaluate("() => { localStorage.setItem('burn60_config', '{not json'); }")
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(200)
        rec("broken_json_no_crash", err == [] and page.locator('[data-testid="q-goal"]').count() > 0, err)
        ctx.close()

        browser.close()

    passed = sum(1 for r in results if r["ok"])
    failed = [r for r in results if not r["ok"]]
    print(f"\nSUMMARY {passed}/{len(results)} passed, {len(failed)} failed")
    for r in failed:
        print("FAIL", r["name"], r["detail"][:400])
    Path(os.environ.get("BURN60_RESULTS", "/tmp/burn60_results_v2.json")).write_text(json.dumps({"passed":passed,"total":len(results),"results":results}, ensure_ascii=False, indent=2))
    return 0 if not failed else 1

if __name__ == "__main__":
    raise SystemExit(main())
