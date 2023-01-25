# SPDX-FileCopyrightText: 2022 Susumu OTA <1632335+susumuota@users.noreply.github.com>
#
# SPDX-License-Identifier: MIT

from datetime import datetime, timedelta, timezone
import gzip
from itertools import zip_longest
import json
import os
import re
from shlex import quote
import subprocess
import tempfile
import time
import unicodedata

import pandas as pd
import dateutil.parser
from google.cloud import storage
import tweepy
import arxiv
import deepl
import pysbd
from slack_sdk import WebClient
import imgkit

import deeplcache

HTML_TEMPLATE = '''
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

HTML_ITEM_TEMPLATE = '''
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

def generate_html(title, authors, url, trans_texts, summary_texts):
  items = map(
    lambda item: HTML_ITEM_TEMPLATE.format(translation=item[0], source=item[1]),
    zip_longest(trans_texts, summary_texts, fillvalue=''))
  return HTML_TEMPLATE.format(title=title, authors=authors, url=url, content='\n'.join(items))

def load_from_gcs(gcs_bucket, filename):
  blb = gcs_bucket.get_blob(filename)
  if blb and blb.exists():
    with tempfile.TemporaryDirectory() as tmpdir:
      tmpfilename = os.path.join(tmpdir, filename)
      blb.download_to_filename(tmpfilename)
      with gzip.open(tmpfilename, 'rt', encoding='UTF-8') as f:
        return json.load(f)
  return None

def load_from_gcs_with_expired(gcs_bucket, filename, expire_timedelta=None):
  if expire_timedelta is None:
    return load_from_gcs(gcs_bucket, filename)
  expire_dt = datetime.now(timezone.utc) - expire_timedelta
  blb = gcs_bucket.get_blob(filename)
  if blb and blb.exists() and blb.updated and blb.updated > expire_dt:
    return load_from_gcs(gcs_bucket, filename)
  return None

def save_to_gcs(gcs_bucket, filename, obj):
  with tempfile.TemporaryDirectory() as tmpdir:
    tmpfilename = os.path.join(tmpdir, filename)
    with gzip.open(tmpfilename, 'wt', encoding='UTF-8') as f:
      json.dump(obj, f)
    gcs_bucket.blob(filename).upload_from_filename(tmpfilename)

def search_recent_tweets(api, query, since_id=None, page_limit=1):
  """https://docs.tweepy.org/en/stable/client.html#tweepy.Client.search_recent_tweets"""
  def get_unique_list(seq):
    seen = []
    return [x for x in seq if x not in seen and not seen.append(x)]
  max_results = 100
  expansions = ['author_id'] # this makes response.includes['users']
  tweet_fields = ['author_id', 'created_at', 'lang', 'public_metrics', 'referenced_tweets', 'entities']
  tweets = []
  users = []
  meta = {'newest_id': None, 'oldest_id': None, 'result_count': 0, 'next_token': None}
  i = 0
  for response in tweepy.Paginator(api.search_recent_tweets, query=query, max_results=max_results, since_id=since_id, expansions=expansions, tweet_fields=tweet_fields, limit=page_limit, user_auth=False):
    if response.data:  # type: ignore
      tweets.extend([t.data for t in response.data])  # type: ignore
    if response.includes and 'users' in response.includes:  # type: ignore
      users.extend([u.data for u in response.includes['users']])  # type: ignore
    # merge meta
    meta['result_count'] += response.meta['result_count']  # type: ignore
    meta['next_token'] = response.meta['next_token'] if 'next_token' in response.meta else None  # type: ignore
    meta['newest_id'] = response.meta['newest_id'] if 'newest_id' in response.meta and meta['newest_id'] is None else meta['newest_id']  # type: ignore  # TODO: reversed order
    meta['oldest_id'] = response.meta['oldest_id'] if 'oldest_id' in response.meta else meta['oldest_id']  # type: ignore  # TODO: reversed order
    i += 1
    if i % 10 == 0:
      print('search_recent_tweets: ', i, meta)
  return {'data': tweets, 'includes': {'users': get_unique_list(users)}, 'meta': meta}

def convert_to_dfs(tweets):
  """parse result of search_recent_tweets result to DataFrame"""
  def extract(df, field):
    """extract multiple values field"""
    results = []
    if field in df.columns:
      df[['id', field]].apply(lambda x: [results.append({'id': x[0], field: u}) for u in x[1]] if type(x[1]) is list else None, axis=1)
    results_df = pd.json_normalize(results)
    # 'id' must be tweet id
    results_df = results_df.rename(columns={c: re.sub(f'{field}.', r'', c) if c != f'{field}.id' else c for c in results_df.columns}) # type: ignore
    return results_df
  meta_df = pd.json_normalize(tweets['meta'])
  users_df = pd.json_normalize(tweets['includes']['users'])
  users_df = users_df.rename(columns={'id': 'author_id'}) # 'id' must be tweet id
  tweets_df = pd.json_normalize(tweets['data'])
  tweets_df = tweets_df.rename(columns={c: re.sub(r'public_metrics\.|entities\.', r'', c) for c in tweets_df.columns}) # type: ignore
  fields = ['urls', 'hashtags', 'mentions', 'annotations', 'cashtags', 'referenced_tweets']
  results = {'meta': meta_df, 'users': users_df}
  for f in fields:
    results[f] = extract(tweets_df, f)
  tweets_df = tweets_df.drop(columns=[f for f in fields if f in tweets_df.columns])
  results['tweets'] = tweets_df
  return results

def expand_tweets_text(tweets_df, urls_df):
  results = []
  for tweet_id, text in zip(tweets_df['id'], tweets_df['text']):
    u = urls_df[urls_df['id'] == tweet_id]
    expanded_text = text
    for url, expanded_url, display_url in zip(u['url'], u['expanded_url'], u['display_url']):
      expanded_text = expanded_text.replace(url, f'<{expanded_url}|{display_url}>') # for slack
    results.append({'id': tweet_id, 'expanded_text': expanded_text})
  return results

# https://arxiv.org/help/arxiv_identifier
ARXIV_URL_PATTERN = re.compile(r'^https?://arxiv\.org/(abs|pdf)/([0-9]{4}\.[0-9]{4,6})(v[0-9]+)?(\.pdf)?$')

def get_arxiv_stats(tweets_df, users_df, urls_df):
  urls = urls_df[['expanded_url', 'unwound_url']].apply(lambda x: x[1] if x[1] != 0 else x[0], axis=1)
  arxiv_ids_df = pd.concat([urls_df['id'], urls.str.extract(ARXIV_URL_PATTERN)[1].rename('arxiv_id')], axis=1).dropna().drop_duplicates()
  arxiv_ids_group = pd.merge(arxiv_ids_df, pd.merge(tweets_df, users_df, on='author_id'), on='id').groupby('arxiv_id')
  arxiv_ids_sum = arxiv_ids_group.sum(numeric_only=True).reset_index()
  arxiv_ids_count = arxiv_ids_group['id'].count().reset_index().rename(columns={'id': 'tweet_count'})
  arxiv_stats_df = pd.concat([arxiv_ids_sum, arxiv_ids_count['tweet_count']], axis=1).sort_values(by=['like_count', 'retweet_count', 'quote_count', 'reply_count', 'tweet_count'], ascending=False)
  #arxiv_tweets_df = pd.merge(arxiv_ids_df, pd.merge(tweets_df, users_df, on='author_id'), on='id') # fast
  expanded_text_df = pd.json_normalize(expand_tweets_text(tweets_df, urls_df)) # TODO: too slow
  arxiv_tweets_df = pd.merge(pd.merge(arxiv_ids_df, pd.merge(tweets_df, users_df, on='author_id'), on='id'), expanded_text_df, on='id')
  return {'arxiv_stats': arxiv_stats_df, 'arxiv_tweets': arxiv_tweets_df}

def arxiv_result_to_dict(r):
  m = ARXIV_URL_PATTERN.match(r.entry_id)
  arxiv_id = m.group(2) if m else None
  assert arxiv_id != None
  arxiv_id_v = m.group(2) + m.group(3) if m else None
  assert arxiv_id_v != None
  return {
    'arxiv_id': arxiv_id,
    'arxiv_id_v': arxiv_id_v,
    'entry_id': r.entry_id,
    'updated': str(r.updated), # TODO
    'published': str(r.published), # TODO
    'title': r.title,
    'authors': [str(a) for a in r.authors],
    'summary': r.summary,
    'comment': r.comment,
    'journal_ref': r.journal_ref,
    'doi': r.doi,
    'primary_category': r.primary_category,
    'categories': [str(c) for c in r.categories],
    'links': [str(l) for l in r.links],
    'pdf_url': r.pdf_url
  }

def get_arxiv_contents(id_list, chunk_size=100):
  rs = []
  cdr = id_list
  for i in range(1+len(id_list)//chunk_size):
    car = cdr[:chunk_size]
    cdr = cdr[chunk_size:]
    if len(car) > 0:
      try:
        search = arxiv.Search(id_list=car, max_results=len(car))
        r = list(search.results())
        rs.extend(r)
        print('search_arxiv_contents: ', i, len(r), len(rs))
      except Exception as e:
        print(e)
  return [arxiv_result_to_dict(r) for r in rs]

def translate_arxiv(dlc, df, target_lang, max_summary):
  seg = pysbd.Segmenter(language='en', clean=False)
  print('translate_arxiv: before: ', len(dlc.cache))
  print(dlc.translator.get_usage())
  for arxiv_id, summary in zip(df['arxiv_id'], df['summary']):
    summary = summary.replace('\n', ' ')[:max_summary]
    summary_texts = seg.segment(summary)
    trans_texts, trans_ts = dlc.translate_text(summary_texts, target_lang, arxiv_id)
    print('translate_arxiv: ', arxiv_id, sum([len(s) for s in summary_texts]), sum([len(t) for t in trans_texts]), trans_ts)
  print('translate_arxiv: after: ', len(dlc.cache))
  print(dlc.translator.get_usage())
  return dlc

def post_to_slack(api, channel, df, arxiv_tweets_df, dlc, max_summary):
  df = df[::-1]  # reverse order
  def strip(s, l):
    return s[:l-3] + '...' if len(s) > l else s
  text = f'Top {len(df)} most popular arXiv papers in the last 7 days'
  blocks = [{'type': 'header', 'text': {'type': 'plain_text', 'text': text}}]
  api.chat_postMessage(channel=channel, text=text, blocks=blocks)
  time.sleep(1)
  seg = pysbd.Segmenter(language='en', clean=False)
  twenty_three_hours_ago = datetime.now(timezone.utc) - timedelta(hours=23)
  for i, (arxiv_id, updated, title, summary, authors, comment, primary_category, categories, like_count, retweet_count, quote_count, replay_count, tweet_count) in enumerate(zip(df['arxiv_id'], df['updated'], df['title'], df['summary'], df['authors'], df['comment'], df['primary_category'], df['categories'], df['like_count'], df['retweet_count'], df['quote_count'], df['reply_count'], df['tweet_count'])):
    summary = summary.replace('\n', ' ')[:max_summary]
    summary_texts = seg.segment(summary)
    first_summary = summary_texts[0][:200] # sometimes pysbd failed to split
    translation_md = None
    is_new = False
    trans = dlc.get(arxiv_id, None)
    if trans is not None:
      trans_texts, trans_ts = trans
      first_summary = trans_texts[0][:200] # sometimes pysbd failed to split
      is_new = True if twenty_three_hours_ago < datetime.fromisoformat(trans_ts) else False
      # assert len(summary_texts) == len(trans_texts) # this rarely happen
      if len(summary_texts) != len(trans_texts):
        print('different texts length', arxiv_id, len(summary_texts), len(trans_texts))
      translation_md = '\n\n'.join(trans_texts)
      translation_md = strip(translation_md, 3000) # must be less than 3001 characters
    new_md = f':new: ' if is_new else ''
    title_md = strip(title, 200)
    categories_md = avoid_auto_link(' | '.join([c for c in [primary_category] + [c for c in categories if c != primary_category and re.match(r'\w+\.\w+$', c)]]))
    stats_md = f'_*{like_count}* Likes, {retweet_count} Retweets, {quote_count} Quotes, {replay_count} Replies, {tweet_count} Tweets_'
    updated_md = dateutil.parser.isoparse(updated).strftime('%d %b %Y')
    blocks = [{'type': 'section', 'text': {'type': 'mrkdwn', 'text': f'[{len(df)-i}/{len(df)}] {new_md}*{title_md}*\n{stats_md}, {categories_md}, {updated_md}\n{first_summary}'}}]
    response = api.chat_postMessage(channel=channel, text=title_md, blocks=blocks)
    time.sleep(1)
    ts = response['ts']
    if translation_md is not None:
      blocks = [{'type': 'section', 'text': {'type': 'mrkdwn', 'text': translation_md}}]
      response = api.chat_postMessage(channel=channel, text=title_md, blocks=blocks, thread_ts=ts)
      time.sleep(1)
    authors_md = strip(', '.join(authors), 1000)
    comment_md = f'\n\n*Comments*: {strip(comment, 1000)}\n\n' if comment else ''
    abs_md = f'<https://arxiv.org/abs/{arxiv_id}|abs>'
    pdf_md = f'<https://arxiv.org/pdf/{arxiv_id}.pdf|pdf>'
    tweets_md = f'<https://twitter.com/search?q=arxiv.org%2Fabs%2F{arxiv_id}%20OR%20arxiv.org%2Fpdf%2F{arxiv_id}.pdf|Tweets>'
    blocks = [{'type': 'section', 'text': {'type': 'mrkdwn', 'text': f'*Links*: {abs_md}, {pdf_md}, {tweets_md}\n\n*Authors*: {authors_md}{comment_md}'}}]
    response = api.chat_postMessage(channel=channel, text=title_md, blocks=blocks, thread_ts=ts)
    time.sleep(1)
    top_n_tweets = arxiv_tweets_df.query(f'arxiv_id == "{arxiv_id}" and like_count > 0 and (like_count + retweet_count + quote_count + reply_count) > 4').sort_values(by=['like_count', 'retweet_count', 'quote_count', 'reply_count'], ascending=False).head(5) # TODO
    post_to_slack_tweets(api, channel, ts, top_n_tweets)
    print('post_to_slack: ', f'[{len(df)-i}/{len(df)}]')

def post_to_slack_tweets(api, channel, ts, df):
  for i, (tweet_id, expanded_text, created_at, username, name, like_count, retweet_count, quote_count, replay_count) in enumerate(zip(df['id'], df['expanded_text'], df['created_at'], df['username'], df['name'], df['like_count'], df['retweet_count'], df['quote_count'], df['reply_count'])):
    blocks = []
    stats_md = f'_*{like_count}* Likes, {retweet_count} Retweets, {quote_count} Quotes, {replay_count} Replies_'
    created_at_md = dateutil.parser.isoparse(created_at).strftime('%d %b')
    url_md = f'<https://twitter.com/{username}/status/{tweet_id}|{created_at_md}>'
    blocks = [{'type': 'section', 'text': {'type': 'mrkdwn', 'text': f'({i+1}/{len(df)}) {stats_md}, {url_md}\n'}}]
    response = api.chat_postMessage(channel=channel, text=url_md, thread_ts=ts, blocks=blocks)
    time.sleep(1)

def download_arxiv_pdf(arxiv_id, tmp_dir):
  dir = quote(tmp_dir)
  output = quote(f'{arxiv_id}.pdf')
  url = quote(f'https://arxiv.org/pdf/{arxiv_id}.pdf')
  result = subprocess.run(f'aria2c -q -x5 -k1M -d {dir} -o {output} {url}', shell=True)
  assert result.returncode == 0  # TODO
  return os.path.join(tmp_dir, f'{arxiv_id}.pdf')

def pdf_to_png(pdf_filename):
  filename = quote(pdf_filename)
  result = subprocess.run(f'pdftoppm -q -png -singlefile -scale-to-x 1200 -scale-to-y -1 {filename} {filename}', shell=True)
  assert result.returncode == 0  # TODO
  return f'{pdf_filename}.png'

def html_to_image(html, image_filename):
  result = imgkit.from_string(html, image_filename, options={ 'width': 1200, 'quiet': '' })
  assert result == True  # TODO
  return image_filename

def avoid_auto_link(text):
  """replace period to one dot leader to avoid auto link.
  https://shkspr.mobi/blog/2015/01/how-to-stop-twitter-auto-linking-urls/"""
  return text.replace('.', '․')

def get_char_width(c):
  return 2 if unicodedata.east_asian_width(c) in 'FWA' else 1

def len_tweet(text):
  return sum(map(get_char_width, text))

def strip_tweet(text, max_length=280, dots='...'):
  length = max_length - (len(dots) if dots else 0)
  buf = []
  count = 0
  for c in text:
    width = get_char_width(c)
    if count + width > length:
      return ''.join(buf) + (dots if dots else '')
    buf.append(c)
    count += width
  return text

def upload_first_page_to_twitter(api_v1, arxiv_id):
  with tempfile.TemporaryDirectory() as tmp_dir:
    pdf_filename = download_arxiv_pdf(arxiv_id, tmp_dir)
    first_page_filename = pdf_to_png(pdf_filename)
    if os.path.isfile(first_page_filename):
      media = api_v1.media_upload(first_page_filename)
      return media.media_id
  return None

def upload_translation_to_twitter(api_v1, arxiv_id, title, authors, stats, trans_texts, summary_texts):
  html_text = generate_html(title, authors, stats, trans_texts, summary_texts)
  with tempfile.TemporaryDirectory() as tmp_dir:
    trans_filename = os.path.join(tmp_dir, f'{arxiv_id}.trans.jpg')
    trans_filename = html_to_image(html_text, trans_filename)
    if os.path.isfile(trans_filename):
      media = api_v1.media_upload(trans_filename)
      return media.media_id
  return None

def post_to_twitter(api_v1, api_v2, df, arxiv_tweets_df, dlc, max_summary):
  df = df[::-1]  # reverse order
  twenty_three_hours_ago = datetime.now(timezone.utc) - timedelta(hours=23)
  seg = pysbd.Segmenter(language='en', clean=False)
  for i, (arxiv_id, updated, title, summary, authors, comment, primary_category, categories, like_count, retweet_count, quote_count, replay_count, tweet_count) in enumerate(zip(df['arxiv_id'], df['updated'], df['title'], df['summary'], df['authors'], df['comment'], df['primary_category'], df['categories'], df['like_count'], df['retweet_count'], df['quote_count'], df['reply_count'], df['tweet_count'])):
    trans_texts, trans_ts = dlc.get(arxiv_id, None)
    # only post new papers
    if not (twenty_three_hours_ago < datetime.fromisoformat(trans_ts)):
      continue
    trans_text = ''.join(trans_texts)
    summary_texts = seg.segment(summary.replace('\n', ' ')[:max_summary])
    summary_text = ' '.join(summary_texts)
    new_md = '🆕' if twenty_three_hours_ago < datetime.fromisoformat(trans_ts) else ''
    authors_md = ', '.join(authors)
    categories_md = avoid_auto_link(' | '.join([c for c in [primary_category] + [c for c in categories if c != primary_category and re.match(r'\w+\.\w+$', c)]]))
    stats_md = f'{like_count} Likes, {retweet_count} Retweets, {quote_count} Quotes, {replay_count} Replies, {tweet_count} Tweets'
    updated_md = dateutil.parser.isoparse(updated).strftime('%d %b %Y')
    title_md = title
    abs_md = f'https://arxiv.org/abs/{arxiv_id}'
    media_ids = []
    first_page_media_id = upload_first_page_to_twitter(api_v1, arxiv_id)
    if first_page_media_id:
      api_v1.create_media_metadata(first_page_media_id, strip_tweet(summary_text, 1000))
      media_ids.append(first_page_media_id)
    text = f'[{len(df)-i}/{len(df)}] {stats_md}\n{abs_md} {categories_md}, {updated_md}\n\n{new_md}{title_md}\n\n{authors_md}'
    prev_tweet_id = None
    try:
      response = api_v2.create_tweet(text=strip_tweet(text, 280), user_auth=True, media_ids=media_ids if len(media_ids) > 0 else None)
      prev_tweet_id = response.data['id']
    except Exception as e:
      print(e)
    time.sleep(1)
    top_n_tweets = arxiv_tweets_df.query(f'arxiv_id == "{arxiv_id}" and (like_count + retweet_count + quote_count + reply_count) > 4').sort_values(by=['like_count', 'retweet_count', 'quote_count', 'reply_count'], ascending=False).head(5) # TODO
    prev_tweet_id = post_to_twitter_tweets(api_v2, prev_tweet_id, arxiv_id, top_n_tweets)
    media_ids = []
    translation_media_id = upload_translation_to_twitter(api_v1, arxiv_id, title_md, authors_md, abs_md, trans_texts, summary_texts)
    if translation_media_id:
      api_v1.create_media_metadata(translation_media_id, strip_tweet(trans_text, 1000))
      media_ids.append(translation_media_id)
    text = f'{abs_md}\n{trans_text}'
    try:
      response = api_v2.create_tweet(text=strip_tweet(text, 280), user_auth=True, media_ids=media_ids if len(media_ids) > 0 else None, in_reply_to_tweet_id=prev_tweet_id)
    except Exception as e:
      print(e)
    print('post_to_twitter: ', f'[{len(df)-i}/{len(df)}]')

def post_to_twitter_tweets(api_v2, prev_tweet_id, arxiv_id, df):
  for i, (tweet_id, expanded_text, created_at, username, name, like_count, retweet_count, quote_count, replay_count) in enumerate(zip(df['id'], df['expanded_text'], df['created_at'], df['username'], df['name'], df['like_count'], df['retweet_count'], df['quote_count'], df['reply_count'])):
    stats_md = f'{like_count} Likes, {retweet_count} Retweets, {quote_count} Quotes, {replay_count} Replies'
    created_at_md = dateutil.parser.isoparse(created_at).strftime('%d %b %Y')
    abs_md = f'https://arxiv.org/abs/{arxiv_id}'
    url_md = f'https://twitter.com/{username}/status/{tweet_id}'
    text = f'({i+1}/{len(df)}) {stats_md}, {created_at_md}\n{abs_md}\n\n{url_md}\n'
    try:
      response = api_v2.create_tweet(text=strip_tweet(text, 280), user_auth=True, in_reply_to_tweet_id=prev_tweet_id)
      prev_tweet_id = response.data['id']
    except Exception as e:
      print(e)
    time.sleep(1)
  return prev_tweet_id

def summarize(tweepy_api_v2, query, since_id, page_limit):
  # retrieve tweets by Twitter API
  tweets_raw = search_recent_tweets(tweepy_api_v2, query, since_id=since_id, page_limit=page_limit)
  print('search_recent_tweets: ', len(tweets_raw['data']), len(tweets_raw['includes']['users']), tweets_raw['meta'])

  # convert tweets to DataFrame
  tweets_dfs = convert_to_dfs(tweets_raw)
  print('convert_to_dfs: ', len(tweets_dfs['tweets']), len(tweets_dfs['users']), tweets_dfs['meta'].values.tolist())

  # analyze tweets and create stats of arxiv urls
  arxiv_stats = get_arxiv_stats(tweets_dfs['tweets'], tweets_dfs['users'], tweets_dfs['urls'])
  arxiv_stats_df = arxiv_stats['arxiv_stats']
  arxiv_tweets_df = arxiv_stats['arxiv_tweets']
  arxiv_ids = arxiv_stats['arxiv_stats']['arxiv_id'].tolist()
  print('get_arxiv_stats: ', len(arxiv_stats_df), len(arxiv_tweets_df))

  # download contents of arxiv papers
  arxiv_contents = get_arxiv_contents(arxiv_ids)
  arxiv_contents_df = pd.json_normalize(arxiv_contents)
  print('get_arxiv_contents: ', len(arxiv_contents_df))

  # merge stats and contents
  arxiv_df = pd.merge(arxiv_stats_df, arxiv_contents_df, on='arxiv_id')

  return arxiv_df, arxiv_tweets_df

def main():
  query = '"arxiv.org" -is:retweet'
  since_id = None
  page_limit = int(os.getenv('SEARCH_PAGE_LIMIT', 1))
  deepl_target_lang = 'JA'
  notify_top_n = int(os.getenv('NOTIFY_TOP_N', 5))

  tweepy_api_v2 = tweepy.Client(
    bearer_token=os.getenv('TWITTER_BEARER_TOKEN'),
    consumer_key=os.getenv('TWITTER_API_KEY'),
    consumer_secret=os.getenv('TWITTER_API_KEY_SECRET'),
    access_token=os.getenv('TWITTER_ACCESS_TOKEN'),
    access_token_secret=os.getenv('TWITTER_ACCESS_TOKEN_SECRET'),
    wait_on_rate_limit=True)

  # because media_upload is only available on api v1.
  tweepy_api_v1 = tweepy.API(
    tweepy.OAuth1UserHandler(
      consumer_key=os.getenv('TWITTER_API_KEY'),
      consumer_secret=os.getenv('TWITTER_API_KEY_SECRET'),
      access_token=os.getenv('TWITTER_ACCESS_TOKEN'),
      access_token_secret=os.getenv('TWITTER_ACCESS_TOKEN_SECRET')),
    wait_on_rate_limit=True)

  gcs_bucket = storage.Client().bucket(os.getenv('GCS_BUCKET_NAME'))

  deepl_api = deepl.Translator(os.getenv('DEEPL_AUTH_KEY'))  # type: ignore

  slack_api = WebClient(os.getenv('SLACK_BOT_TOKEN'))
  slack_channel = os.getenv('SLACK_CHANNEL')

  # try to load from cache
  arxiv_dict = load_from_gcs_with_expired(
    gcs_bucket, 'arxiv_dict.json.gz', expire_timedelta=timedelta(hours=23))
  arxiv_tweets_dict = load_from_gcs_with_expired(
    gcs_bucket, 'arxiv_tweets_dict.json.gz', expire_timedelta=timedelta(hours=23))
  if arxiv_dict and arxiv_tweets_dict:
    arxiv_df = pd.json_normalize(arxiv_dict)
    arxiv_tweets_df = pd.json_normalize(arxiv_tweets_dict)
  else:
    # if there is no cache or expired
    arxiv_df, arxiv_tweets_df = summarize(tweepy_api_v2, query, since_id, page_limit)
    save_to_gcs(gcs_bucket, 'arxiv_dict.json.gz', arxiv_df.to_dict(orient='records'))
    assert arxiv_df.equals(pd.json_normalize(load_from_gcs(gcs_bucket, 'arxiv_dict.json.gz')))  # type: ignore
    save_to_gcs(gcs_bucket, 'arxiv_tweets_dict.json.gz', arxiv_tweets_df.to_dict(orient='records'))
    assert arxiv_tweets_df.equals(pd.json_normalize(load_from_gcs(gcs_bucket, 'arxiv_tweets_dict.json.gz'))) # type: ignore
  print('main: ', len(arxiv_df), len(arxiv_tweets_df))

  # pickup top N papers
  arxiv_df_top_n = arxiv_df.head(notify_top_n)

  # translate summary text
  dlc = deeplcache.DeepLCache(deepl_api)  # type: ignore
  try:
    dlc.load_from_gcs(gcs_bucket, 'deepl_cache.json.gz')
  except Exception as e:
    print(e)
  dlc = translate_arxiv(dlc, arxiv_df_top_n, deepl_target_lang, 2000) # TODO
  dlc.clear_cache(expire_timedelta=timedelta(days=30))
  dlc.save_to_gcs(gcs_bucket, 'deepl_cache.json.gz')

  # post to Slack
  post_to_slack(slack_api, slack_channel, arxiv_df_top_n, arxiv_tweets_df, dlc, 2000) # TODO

  # post to Twitter. it needs api v1 because media_upload is only available on api v1.
  post_to_twitter(tweepy_api_v1, tweepy_api_v2, arxiv_df_top_n, arxiv_tweets_df, dlc, 2000) # TODO


if __name__ == '__main__':
  main()
