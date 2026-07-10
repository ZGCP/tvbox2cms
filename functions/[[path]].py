"""
TVbox → 苹果CMS V10 转换
Cloudflare Pages (Python Workers) 版本
"""
import json
import asyncio
from collections import defaultdict
from urllib.parse import parse_qs

SOURCES = [
    {"name": "盒子迷", "url": "https://xn--gmq004i.top/%E7%A6%81%E6%AD%A2%E8%B4%A9%E5%8D%96"},
    {"name": "wzh多仓", "url": "https://gh-proxy.com/https://raw.githubusercontent.com/wzh15802/tvbox/main/tv.json"},
    {"name": "王二小备用1", "url": "https://9280.kstore.vip/newwex.json"},
    {"name": "王二小备用2", "url": "https://9280.kstore.space/wex.json"},
    {"name": "驸马", "url": "http://fmys.top/fmys.json"},
    {"name": "极客小盒", "url": "https://gist.githubusercontent.com/ph7368/905ad3256f462dc6281acb00ca40a4fe/raw/XH.txt"},
]

def normalise_pic(url):
    if not url: return ""
    url = str(url).strip()
    if url.startswith("//"): return "https:" + url
    return url

def normalise_vod(item, source=""):
    vodid = str(item.get("vodid") or item.get("id") or item.get("dxId") or "")
    name = str(item.get("vodname") or item.get("name") or item.get("title") or f"未知{vodid}")
    pic = normalise_pic(item.get("vodpic") or item.get("pic") or item.get("cover") or item.get("thumb") or "")
    typename = str(item.get("typename") or item.get("type") or item.get("category") or "其他")
    note = str(item.get("vodremarks") or item.get("remarks") or item.get("note") or "")
    actor = item.get("vodactor") or item.get("actor") or item.get("actors") or ""
    director = item.get("voddirector") or item.get("director") or item.get("directors") or ""
    desc = item.get("vodcontent") or item.get("content") or item.get("describe") or item.get("des") or ""
    
    if isinstance(desc, list): desc = " ".join(str(d) for d in desc)
    if isinstance(actor, list): actor = ",".join(str(a) for a in actor)
    if isinstance(director, list): director = ",".join(str(d) for d in director)
    
    player = item.get("player") or item.get("vods") or item.get("urls") or []
    all_urls = []
    
    if isinstance(player, list):
        for p in player:
            if isinstance(p, str): all_urls.append({"note":"","url":p,"type":""})
            elif isinstance(p, dict): all_urls.append({"note":str(p.get("name",p.get("title",p.get("note","")))),"url":p.get("url",""),"type":str(p.get("type",p.get("from","")))})
    elif isinstance(player, dict):
        for src, episodes in player.items():
            if isinstance(episodes, list):
                for ep in episodes:
                    if isinstance(ep, dict): all_urls.append({"note":str(ep.get("name","")),"url":ep.get("url",""),"type":src})
                    else: all_urls.append({"note":"","url":str(ep),"type":src})
    
    by_source = defaultdict(list)
    for p in all_urls:
        src = p["type"].strip() or "unknown"
        url = p["url"].strip()
        note2 = p["note"].strip()
        if url: by_source[src].append(f"{note2}${url}" if note2 else url)
    
    parts = [f"{src}${'#'.join(urls)}" for src, urls in by_source.items()]
    play_source = "$$#".join(parts)
    play_url = "#".join(p["url"] for p in all_urls if p["url"].strip())
    
    return {
        "vod_id": vodid, "vod_name": name, "vod_pic": pic, "type_name": typename,
        "vod_remarks": note, "vod_actor": str(actor), "vod_director": str(director),
        "vod_content": str(desc), "vod_play_from": play_source, "vod_play_url": play_url,
        "_source": source
    }

async def fetch_source(source):
    name, url = source["name"], source["url"]
    try:
        res = await fetch(url, {"headers": {"User-Agent": "Mozilla/5.0"}, "timeout": 15000})
        if res.status != 200: return [], f"HTTP {res.status}"
        text = await res.text()
        data = json.loads(text)
        
        raw = data if isinstance(data, list) else data.get("list",[]) or data.get("data",[]) or data.get("results",[]) or []
        if not raw and isinstance(data, dict):
            for v in data.values():
                if isinstance(v,list) and v and isinstance(v[0],dict) and ("name" in v[0] or "title" in v[0]):
                    raw=v; break
        
        vods = []
        for item in raw:
            if not isinstance(item, dict): continue
            sub = item.get("list") or item.get("videos") or item.get("data") or []
            if sub:
                for v in sub:
                    if isinstance(v, dict): vods.append(normalise_vod(v, name))
            else: vods.append(normalise_vod(item, name))
        return vods, None
    except Exception as e: return [], str(e)

async def fetch_all_sources():
    tasks = [fetch_source(s) for s in SOURCES]
    results = await asyncio.gather(*tasks)
    all_vods, errors = [], []
    for i, (vods, err) in enumerate(results):
        if err: errors.append(f"{SOURCES[i]['name']}:{err}")
        else: all_vods.extend(vods)
    
    seen, unique = set(), []
    for v in all_vods:
        key = (v["vod_id"] or v["vod_name"], v["_source"])
        if key not in seen: seen.add(key); unique.append(v)
    return unique, errors

def build_types(vods):
    m = {}
    for v in vods:
        t = v.get("type_name","其他")
        if t not in m: m[t] = len(m)+1
    return [{"type_id":tid,"type_name":name} for name,tid in m.items()]

def make_response(data, status=200):
    return Response(
        json.dumps(data, ensure_ascii=False),
        status=status,
        headers={"Content-Type":"application/json; charset=utf-8","Access-Control-Allow-Origin":"*"}
    )

# ===== 主入口 =====
async def on_fetch(request):
    url = request.url
    path = url.path
    query = parse_qs(url.query)

    if path in ("/", ""):
        return make_response({
            "code":1,"msg":"TVbox → 苹果CMS V10",
            "endpoints":{
                "/api.php/provide/vod":"视频列表",
                "/api.php/provide/search":"搜索",
                "/api.php/provide/categories":"分类"
            },
            "sources_count":len(SOURCES)
        })

    if path == "/refresh":
        vods, errors = await fetch_all_sources()
        return make_response({"code":1,"msg":f"刷新完成{len(vods)}条","errors":errors,"preview":vods[:5]})

    if "/provide/vod" in path:
        vods, _ = await fetch_all_sources()
        t = query.get("t", [""])[0]
        pg = int(query.get("pg", ["1"])[0])
        limit = min(int(query.get("limit", ["20"])[0]), 100)
        ids = query.get("ids", [""])[0]
        q = query.get("q", [""])[0] or query.get("wd", [""])[0]

        if ids:
            id_list = [i.strip() for i in ids.split(",") if i.strip()]
            r = [x for x in vods if x["vod_id"] in id_list]
            return make_response({"code":1,"page":1,"pagecount":1,"total":len(r),"list":r})

        if q:
            r = [x for x in vods if q.lower() in x["vod_name"].lower()]
            return make_response({"code":1,"page":1,"pagecount":1,"total":len(r),"list":r})

        f = [x for x in vods if x.get("type_name")==t] if t else vods
        total = len(f)
        pc = max(1, (total + limit - 1) // limit)
        start = (pg - 1) * limit
        return make_response({
            "code":1,"page":pg,"pagecount":pc,"limit":limit,"total":total,
            "list":f[start:start+limit]
        })

    if "/provide/search" in path:
        q = query.get("wd", [""])[0] or query.get("q", [""])[0]
        if not q: return make_response({"code":0,"msg":"缺少搜索词","list":[]})
        vods, _ = await fetch_all_sources()
        r = [x for x in vods if q.lower() in x["vod_name"].lower()]
        return make_response({"code":1,"page":1,"pagecount":1,"total":len(r),"list":r})

    if any(k in path for k in ("/provide/categories","/provide/category","/provide/type")):
        vods, _ = await fetch_all_sources()
        return make_response({"code":1,"list":build_types(vods)})

    return make_response({"code":404,"msg":"Not Found"},404)
