"""No browser network needed. Test the actual index-review UI with deterministic data."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT/'official-index.html').read_text()
CSS = (ROOT/'official-index.css').read_text()
JS = (ROOT/'official-index.js').read_text()
BASE = json.loads((ROOT/'data/moex_official_index.json').read_text())


def run():
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        ctx=browser.new_context(viewport={'width':390,'height':820},device_scale_factor=1,is_mobile=True,has_touch=True)
        def mount(data):
            page=ctx.new_page()
            errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.set_content(HTML.replace('<link rel="stylesheet" href="official-index.css">','<style>'+CSS+'</style>').replace('<script type="module" src="./official-index.js"></script>',''))
            page.evaluate('(data)=>{window.fetch=async()=>({ok:true,json:async()=>data})}',data)
            page.evaluate(JS)
            return page,errors
        page,e=mount(BASE)
        assert '尚未完成首次官方 CSV 同步' in page.locator('#status').inner_text()
        assert '不代表沒有國考試題' in page.locator('#results').inner_text()
        assert not e,e
        page.close()
        item={'id':'moex-a','year_roc':'114','exam':'<img src=x onerror=alert(1)> 高考三級','grade':'三等','subject':'中華民國憲法','focus_subjects':['憲法'],'classification':'subject_named','question_type':'測試題','question_url':'https://wwwq.moex.gov.tw/ExamQ.pdf','answer_url':'https://wwwc.moex.gov.tw/ExamA.pdf','groups':['法制'],'answer_verification':'not_verified'}
        item2={**item,'id':'moex-b','year_roc':'113','subject':'民法','focus_subjects':['民法'],'question_url':'https://wwwq.moex.gov.tw/CivilQ.pdf','answer_url':''}
        test={**BASE,'status':'index_only_unverified_answers','items':[item,item2],'disclaimer':'僅索引，答案未核驗'}
        page,e=mount(test)
        assert '2 份' in page.locator('#status').inner_text()
        assert page.locator('.paper').count()==2
        assert page.locator('.paper img').count()==0, 'unsafe HTML injection'
        assert '<img src=' in page.locator('.paper').first.inner_text()
        assert page.get_by_text('官方答案文件（尚未核驗）').count()==1
        page.locator('#subject').select_option('民法')
        assert page.locator('.paper').count()==1
        page.locator('#subject').select_option('全部')
        page.locator('#search').fill('不可能的考試')
        assert page.locator('.paper').count()==0
        assert not e,e
        page.close();browser.close()
    print('OFFICIAL INDEX BROWSER PASS: empty status, candidates, filters, safe rendering')

if __name__=='__main__': run()
