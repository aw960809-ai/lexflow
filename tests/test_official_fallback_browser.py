"""Read-only mobile UI acceptance test for isolated official-page fallback data."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE=Path(__file__).resolve().parents[1]
HTML=(BASE/'official-index.html').read_text()
CSS=(BASE/'official-index.css').read_text()
JS=(BASE/'official-index.js').read_text()
PRIMARY=json.loads((BASE/'data/moex_official_index.json').read_text())
FALLBACK=json.loads((BASE/'data/moex_official_fallback.json').read_text())


def run():
    mock={**FALLBACK,
        'status':'fallback_official_page_links_unverified',
        'items':[
            dict(id='moex-page-first',year_roc='114',exam='114年司法特考',grade='司法四等',
                 subject='民法概要',focus_subjects=['民法'],classification='subject_named',
                 question_type='題型待原卷核對（可能包含申論及測驗）',
                 question_url='https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?c=201&code=114120&q=1&s=0405&t=Q',
                 answer_url='https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?c=201&code=114120&q=1&s=0405&t=S',
                 answer_correction_url='',groups=['司法四等考試_法院書記官類科'],
                 source_page_url='https://wwwq.moex.gov.tw/exam/wFrmExamQandASearch.aspx?e=114120&y=2025')],
        'disclaimer':'候審官方頁面索引，答案未逐題查核'}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        ctx=browser.new_context(viewport={'width':390,'height':844},device_scale_factor=1,is_mobile=True,has_touch=True)
        page=ctx.new_page()
        errors=[]
        page.on('pageerror',lambda e: errors.append(str(e)))
        page.set_content(HTML.replace('<link rel="stylesheet" href="official-index.css">','<style>'+CSS+'</style>').replace('<script type="module" src="./official-index.js"></script>',''))
        page.evaluate('(models)=>{window.fetch=async(u)=>({ok:true,json:async()=>u.includes("fallback")?models[1]:models[0]})}',[PRIMARY,mock])
        page.evaluate(JS)
        page.get_by_text('已建立 1 份官方個別考試頁面備援索引').wait_for()
        assert page.locator('.paper').count()==1
        assert page.get_by_text('官方答案文件（尚未核驗）').count()==1
        assert page.get_by_text('官方更正答案文件（尚未核驗）').count()==0
        assert '114年司法特考' in page.locator('#results').inner_text()
        assert '未核對 PDF' in page.locator('#results').inner_text()
        assert page.locator('body').evaluate('e=>e.scrollWidth <= window.innerWidth+2')
        assert not errors, errors
        page.close();browser.close()
    print('OFFICIAL FALLBACK MOBILE BROWSER PASS: two indexes, official link, warnings, no JS errors')

if __name__=='__main__':run()
