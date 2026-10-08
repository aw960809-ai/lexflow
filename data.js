export const OFFICIAL_PAPERS = [
  {id:'moex-114-const',year:114,exam:'司法官／律師第二試',subject:'憲法與行政法',kind:'official',duration:180,title:'114年｜憲法與行政法',url:'https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?c=301&code=114111&q=1&s=0102&t=Q'},
  {id:'moex-114-civil',year:114,exam:'司法官／律師第二試',subject:'民法與民事訴訟法（一）',kind:'official',duration:120,title:'114年｜民法與民事訴訟法（一）',url:'https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?c=301&code=114111&q=1&s=0203&t=Q'},
  {id:'moex-114-criminal',year:114,exam:'司法官／律師第二試',subject:'刑法與刑事訴訟法',kind:'official',duration:180,title:'114年｜刑法與刑事訴訟法',url:'https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?c=301&code=114111&q=1&s=0302&t=Q'},
  {id:'moex-113-const',year:113,exam:'司法官／律師第二試',subject:'憲法與行政法',kind:'official',duration:180,title:'113年｜憲法與行政法',url:'https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?c=301&code=113111&q=1&s=0102&t=Q'},
  {id:'moex-113-civil',year:113,exam:'司法官／律師第二試',subject:'民法與民事訴訟法（一）',kind:'official',duration:120,title:'113年｜民法與民事訴訟法（一）',url:'https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?c=301&code=113111&q=1&s=0203&t=Q'},
  {id:'moex-113-criminal',year:113,exam:'司法官／律師第二試',subject:'刑法與刑事訴訟法',kind:'official',duration:180,title:'113年｜刑法與刑事訴訟法',url:'https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?c=301&code=113111&q=1&s=0302&t=Q'}
];

// Original instructional exercises. NOT past-exam questions, official keys, or legal advice.
export const PRACTICE_QUESTIONS = [
  {
    id:'sample-civil-01',year:null,exam:'自編訓練題',subject:'民法',kind:'practice',duration:35,
    title:'通謀虛偽意思表示與不動產交易',
    question:'甲為逃避債權人追索，與友人乙約定以買賣為名義，將甲所有的 A 屋登記移轉予乙，雙方都清楚並無真正買賣與移轉所有權的意思。其後，乙在登記名義仍為乙時，將 A 屋出售予不知甲、乙安排的丙，丙支付價金並辦妥所有權移轉登記。甲主張自己才是所有權人，依民法第 767 條請求丙返還 A 屋。試就甲、乙間行為的效力、丙可能受保護的法律基礎，以及甲的物上請求權，分層分析法律關係。請辨別各階段債權行為與物權行為。',
    points:['先辨別甲乙間買賣及物權行為，逐一檢討法律效力','指出第三人保護相關規範與其適用要件','區分丙取得權利的可能途徑，不可直接跳結論','回到民法第767條之要件作最終判斷'],
    sourceNote:'本題由系統自編，非考選部歷屆原題；爭議法律見解請查核法規及實務。'
  },
  {
    id:'sample-criminal-01',year:null,exam:'自編訓練題',subject:'刑法',kind:'practice',duration:30,
    title:'結果歸責、因果關係與罪責層次',
    question:'甲與乙發生爭執，出手推乙，乙失去平衡倒向車道。此時丙駕車經過，因分心未注意前方而撞及乙，乙受重傷。乙傷勢並非甲單獨推擠所必然造成。試問甲對乙所受傷害可能成立何種刑事責任？請分別討論構成要件該當性、因果關係、客觀歸責、主觀要件，以及可能的競合問題。',
    points:['先設定可能檢討之犯罪類型及主客觀構成要件','辨別自然因果關係與規範性歸責問題','具體討論丙行為是否影響歸責','最後處理違法性、罪責與競合的必要檢討'],
    sourceNote:'本題由系統自編，非考選部歷屆原題；應依現行法及實務進一步確認。'
  },
  {
    id:'sample-const-01',year:null,exam:'自編訓練題',subject:'憲法',kind:'practice',duration:30,
    title:'表意自由與個人隱私權的衡量',
    question:'某公立大學為維護校園秩序，公告禁止學生在公共討論區發布涉及其他學生私人生活的資訊。學生甲因發表校園自治議題評論而遭刪文，該文夾雜乙的個人資訊。甲主張校方措施違反言論自由；乙則主張隱私應受保障。請分析相關基本權、校方行為的憲法審查架構與必要的利益衡量。',
    points:['辨認言論自由、隱私權及公權力介入問題','確認法律保留及限制目的','進行具體比例原則審查而非空泛列舉','處理可能的較小侵害替代措施並作結論'],
    sourceNote:'本題由系統自編，非國家考試歷屆原題。'
  }
];

export const RUBRIC = [
  {key:'issues',label:'爭點辨識',max:20,desc:'辨認主要、次要爭點與前提'},
  {key:'rules',label:'法規與要件',max:25,desc:'正確法條、法律概念及見解'},
  {key:'application',label:'涵攝與論證',max:30,desc:'運用事實、比較見解、論證合理性'},
  {key:'structure',label:'體系與架構',max:15,desc:'分層檢討、層次順序、結構清楚'},
  {key:'conclusion',label:'結論與文字',max:10,desc:'明確結論、文字精準'}
];
export const OFFICIAL_SEARCH_URL = 'https://wwwq.moex.gov.tw/exam/wFrmExamQandASearch.aspx';
export const LAW_SOURCES = [
  {label:'全國法規資料庫',url:'https://law.moj.gov.tw/'},
  {label:'司法院法學資料檢索',url:'https://judgment.judicial.gov.tw/'},
  {label:'憲法法庭',url:'https://cons.judicial.gov.tw/'},
  {label:'考選部考畢試題',url:OFFICIAL_SEARCH_URL}
];
