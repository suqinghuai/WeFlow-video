import os
import sys
import re
import json
import shutil
from datetime import datetime, timezone, timedelta

BEIJING_TZ = timezone(timedelta(hours=8))


def get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def find_html_project(base_dir):
    for item in os.listdir(base_dir):
        item_path = os.path.join(base_dir, item)
        if not os.path.isdir(item_path):
            continue
        for sub in os.listdir(item_path):
            if sub.lower().endswith('.html'):
                html_dir = item_path
                html_file = os.path.join(html_dir, sub)
                videos_dir = os.path.join(html_dir, 'media', 'videos')
                os.makedirs(videos_dir, exist_ok=True)
                return html_dir, html_file, videos_dir
    return None, None, None


def load_messages(html_file):
    with open(html_file, 'r', encoding='utf-8') as f:
        content = f.read()
    pattern = r'window\.WEFLOW_DATA\s*=\s*\[(.+?)\];'
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        raise RuntimeError('未找到 WEFLOW_DATA')
    json_str = '[' + match.group(1) + ']'
    return content, json.loads(json_str)


def collect_mp4s(search_dir):
    mp4s = []
    for root, _, files in os.walk(search_dir):
        for fname in files:
            fl = fname.lower()
            if not fl.endswith('.mp4') or '_raw.mp4' in fl:
                continue
            fpath = os.path.join(root, fname)
            mp4s.append({
                'path': fpath,
                'name': fname,
                'mtime': os.path.getmtime(fpath),
                'size': os.path.getsize(fpath),
            })
    mp4s.sort(key=lambda x: x['mtime'])
    return mp4s


def find_nearest_mp4(mp4s, target_ts):
    lo, hi = 0, len(mp4s) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if mp4s[mid]['mtime'] < target_ts:
            lo = mid + 1
        else:
            hi = mid
    candidates = []
    idx = lo
    for off in range(-2, 3):
        i = idx + off
        if 0 <= i < len(mp4s):
            candidates.append(mp4s[i])
    best, best_diff = None, float('inf')
    for mp4 in candidates:
        diff = abs(mp4['mtime'] - target_ts)
        if diff < best_diff:
            best_diff = diff
            best = mp4
    return best, best_diff


def ts_str(ts):
    return datetime.fromtimestamp(ts, tz=BEIJING_TZ).strftime('%Y-%m-%d %H:%M:%S')


def main():
    base_dir = get_base_dir()
    print(f"程序所在目录: {base_dir}")
    print("-" * 60)

    html_dir, html_file, videos_dir = find_html_project(base_dir)
    if not html_file:
        print("错误：未找到包含HTML文件的子目录")
        input("\n按任意键退出...")
        return

    print(f"HTML文件: {html_file}")
    print(f"HTML目录: {html_dir}")
    print(f"视频输出目录: {videos_dir}")
    print(f"视频源目录: {base_dir}")
    print("-" * 60)

    try:
        html_content, messages = load_messages(html_file)
    except RuntimeError as e:
        print(f"错误：{e}")
        input("\n按任意键退出...")
        return

    video_msgs = [m for m in messages if '[视频]' in m.get('b', '')]
    print(f"共找到视频消息: {len(video_msgs)} 条")
    for vm in video_msgs:
        print(f"  消息 #{vm['i']} - 时间: {ts_str(vm['t'])}")

    print("-" * 60)

    all_mp4s = collect_mp4s(base_dir)
    print(f"共找到mp4视频文件: {len(all_mp4s)} 个 (已排除_raw.mp4)")

    print("-" * 60)

    if not video_msgs:
        print("没有需要处理的视频消息。")
        input("\n按任意键退出...")
        return

    if not all_mp4s:
        print("错误：未找到任何mp4视频文件")
        input("\n按任意键退出...")
        return

    modified_count = 0

    for vm in video_msgs:
        target_ts = vm['t']
        msg_time_str = ts_str(target_ts)
        best_match, best_diff = find_nearest_mp4(all_mp4s, target_ts)

        if not best_match:
            print(f"消息 #{vm['i']} ({msg_time_str}) - 未找到匹配视频\n")
            continue

        mp4_time_str = ts_str(best_match['mtime'])
        diff_min = best_diff / 60
        print(f"消息 #{vm['i']} ({msg_time_str})")
        print(f"  最佳匹配: {best_match['name']}")
        print(f"  文件时间: {mp4_time_str}")
        print(f"  时间差: {diff_min:.1f} 分钟")
        print(f"  文件大小: {best_match['size'] / 1024 / 1024:.2f} MB")

        file_hash = os.path.splitext(best_match['name'])[0]
        new_name = f"{vm['i']}_{file_hash}.mp4"
        dest_path = os.path.join(videos_dir, new_name)

        if not os.path.exists(dest_path):
            shutil.copy2(best_match['path'], dest_path)
            print(f"  已复制 -> media/videos/{new_name}")
        else:
            print(f"  已存在 -> media/videos/{new_name}")

        video_html = (
            f'<div class="message-time">{msg_time_str}</div>'
            f'<div class="message-content">'
            f'<video class="message-media video" controls preload="metadata" '
            f'src="media/videos/{new_name}"></video>'
            f'</div>'
        )

        old_b_escaped = json.dumps(vm['b'], ensure_ascii=False)[1:-1]
        new_b_escaped = json.dumps(video_html, ensure_ascii=False)[1:-1]
        html_content = html_content.replace(old_b_escaped, new_b_escaped)
        modified_count += 1
        print(f"  HTML引用已更新\n")

    if modified_count > 0:
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"完成！已处理 {modified_count} 条视频消息，HTML文件已更新。")
    else:
        print("没有需要处理的视频消息。")

    print(f"\n视频文件位置: {videos_dir}")
    print("请在浏览器中打开HTML文件验证视频是否正常播放。")
    input("\n按任意键退出...")


if __name__ == '__main__':
    main()