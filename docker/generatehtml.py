# SPDX-FileCopyrightText: 2023 Susumu OTA <1632335+susumuota@users.noreply.github.com>
#
# SPDX-License-Identifier: MIT

from datetime import datetime, timedelta, timezone
from itertools import zip_longest
import re

import dateutil.parser


HTML_TRANS_TEMPLATE = '''
<html>
  <head>
    <meta charset="utf-8">
    <style>
      body {{
        font-size: 24px;
        margin: 2em;
      }}
      .translation {{
        color: black;
      }}
      .source {{
        color: blue;
      }}
    </style>
  </head>
  <body>
    <span>{url}</span>
    <h2>
      {title}
    </h2>
    <h4>
      {authors}
    </h4>
    <div>
      {content}
    </div>
  </body>
</html>
'''

HTML_TRANS_ITEM_TEMPLATE = '''
<p class="item">
  <span class="translation">
    {translation}
  </span>
  <br />
  <span class="source">
    {source}
  </span>
</p>
'''

def generate_trans_html(title, authors, url, trans_texts, summary_texts):
  items = map(
    lambda item: HTML_TRANS_ITEM_TEMPLATE.format(translation=item[0], source=item[1]),
    zip_longest(trans_texts, summary_texts, fillvalue=''))
  return HTML_TRANS_TEMPLATE.format(title=title, authors=authors, url=url, content='\n'.join(items))

HTML_TOP_N_TEMPLATE = '''
<html>
  <head>
    <meta charset="utf-8">
    <style>
      body {{
        font-size: 24px;
        margin: 2em;
      }}
    </style>
  </head>
  <body>
    <span>{date}</span>
    <h2>
      {title}
    </h2>
    <div>
      {content}
    </div>
  </body>
</html>
'''

HTML_TOP_N_ITEM_TEMPLATE = '''
<p class="item">
  [{i}/{n}] {new_icon}<b>{title}</b><br />
  <it>{stats}, {categories}, {updated}</it><br />
  <a href="https://arxiv.org/abs/{arxiv_id}">https://arxiv.org/abs/{arxiv_id}</a>
</p>
'''

def generate_top_n_html(page_title, date, df, dlc):
  df = df[::-1]  # normal order (reversed reversed order)
  items = []
  twenty_three_hours_ago = datetime.now(timezone.utc) - timedelta(hours=23)
  for i, (arxiv_id, updated, title, summary, authors, comment, primary_category, categories, like_count, retweet_count, quote_count, replay_count, tweet_count) in enumerate(zip(df['arxiv_id'], df['updated'], df['title'], df['summary'], df['authors'], df['comment'], df['primary_category'], df['categories'], df['like_count'], df['retweet_count'], df['quote_count'], df['reply_count'], df['tweet_count'])):
    trans_texts, trans_ts = dlc.get(arxiv_id, None)
    new_icon = '<b>[New]</b> ' if twenty_three_hours_ago < datetime.fromisoformat(trans_ts) else '' # TODO
    categories = ' | '.join([c for c in [primary_category] + [c for c in categories if c != primary_category and re.match(r'\w+\.\w+$', c)]])
    stats = f'<b>{like_count}</b> Likes, {retweet_count} Retweets, {quote_count} Quotes, {replay_count} Replies, {tweet_count} Tweets'
    updated = dateutil.parser.isoparse(updated).strftime('%d %b %Y')
    items.append(HTML_TOP_N_ITEM_TEMPLATE.format(i=i+1, n=len(df), new_icon=new_icon, title=title, stats=stats, categories=categories, updated=updated, arxiv_id=arxiv_id))
  return HTML_TOP_N_TEMPLATE.format(title=page_title, date=date, content='\n'.join(items))
