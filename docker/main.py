import datetime
import os
import re
import time

import pandas as pd
import dateutil.parser
from google.cloud import storage
import tweepy
import arxiv
import deepl
import pysbd
from slack_sdk import WebClient

import deeplcache

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
  for response in tweepy.Paginator(api.search_recent_tweets, query=query, max_results=max_results, since_id=since_id, expansions=expansions, tweet_fields=tweet_fields, limit=page_limit):
    if response.data:  # type: ignore
      tweets.extend([t.data for t in response.data])  # type: ignore
    if response.includes and 'users' in response.includes:  # type: ignore
      users.extend([u.data for u in response.includes['users']])  # type: ignore
    # merge meta
    meta['result_count'] += response.meta['result_count']  # type: ignore
    meta['next_token'] = response.meta['next_token'] if 'next_token' in response.meta else None  # type: ignore
    meta['newest_id'] = response.meta['newest_id'] if 'newest_id' in response.meta and meta['newest_id'] is None else meta['newest_id']  # type: ignore  # TODO: reversed order
    meta['oldest_id'] = response.meta['oldest_id'] if 'oldest_id' in response.meta else meta['oldest_id']  # type: ignore  # TODO: reversed order
  return {'data': tweets, 'includes': {'users': get_unique_list(users)}, 'meta': meta}

def parse_tweets(tweets):
  """parse result of search_recent_tweets result to DataFrame"""
  def extract(df, field):
    """extract multiple values field"""
    results = []
    if field in df.columns:
      df[['id', field]].apply(lambda x: [results.append({'id': x[0], field: u}) for u in x[1]] if type(x[1]) is list else None, axis=1)
    results_df = pd.json_normalize(results)
    results_df = results_df.fillna(0) # because (np.nan == np.nan) is False
    results_df = results_df.rename(columns={c: re.sub(f'{field}\.', r'', c) if c != f'{field}.id' else c for c in results_df.columns}) # 'id' must be tweet id
    return results_df
  meta_df = pd.json_normalize(tweets['meta'])
  users_df = pd.json_normalize(tweets['includes']['users'])
  users_df = users_df.fillna(0) # because (np.nan == np.nan) is False
  users_df = users_df.rename(columns={'id': 'author_id'}) # 'id' must be tweet id
  tweets_df = pd.json_normalize(tweets['data'])
  tweets_df = tweets_df.fillna(0) # because (np.nan == np.nan) is False
  tweets_df = tweets_df.rename(columns={c: re.sub(r'public_metrics\.|entities\.', r'', c) for c in tweets_df.columns})
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

def parse_arxiv(tweets_df, users_df, urls_df):
  urls = urls_df[['expanded_url', 'unwound_url']].apply(lambda x: x[1] if x[1] != 0 else x[0], axis=1)
  arxiv_ids_df = pd.concat([urls_df['id'], urls.str.extract(ARXIV_URL_PATTERN)[1].rename('arxiv_id')], axis=1).dropna().drop_duplicates()
  arxiv_ids_group = pd.merge(arxiv_ids_df, pd.merge(tweets_df, users_df, on='author_id'), on='id').groupby('arxiv_id')
  arxiv_ids_sum = arxiv_ids_group.sum().reset_index()
  arxiv_ids_count = arxiv_ids_group['id'].count().reset_index().rename(columns={'id': 'tweet_count'})
  arxiv_stats_df = pd.concat([arxiv_ids_sum, arxiv_ids_count['tweet_count']], axis=1).sort_values(by=['like_count', 'retweet_count', 'quote_count', 'reply_count', 'tweet_count'], ascending=False)
  #arxiv_tweets_df = pd.merge(arxiv_ids_df, pd.merge(tweets_df, users_df, on='author_id'), on='id') # fast
  expanded_text_df = pd.json_normalize(expand_tweets_text(tweets_df, urls_df)) # TODO: too slow
  arxiv_tweets_df = pd.merge(pd.merge(arxiv_ids_df, pd.merge(tweets_df, users_df, on='author_id'), on='id'), expanded_text_df, on='id')
  return {'arxiv_stats': arxiv_stats_df, 'arxiv_ids': arxiv_ids_df, 'arxiv_tweets': arxiv_tweets_df}

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

def search_arxiv(id_list, chunk_size=100):
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
        print(i, len(r), len(rs))
      except Exception as e:
        print(e)
  return [arxiv_result_to_dict(r) for r in rs]

def translate_arxiv(dlc, arxiv_stats, arxiv_results, target_lang, top_n, max_summary):
    df = pd.merge(arxiv_stats['arxiv_stats'], pd.json_normalize(arxiv_results), on='arxiv_id').head(top_n)
    seg = pysbd.Segmenter(language='en', clean=False)
    print(len(dlc.cache))
    print(dlc.translator.get_usage())
    for arxiv_id, summary in zip(df['arxiv_id'], df['summary']):
      summary = summary.replace('\n', ' ')[:max_summary]
      summary_texts = seg.segment(summary)
      trans_texts, trans_ts = dlc.translate_text(summary_texts, target_lang, arxiv_id)
      print(arxiv_id, sum([len(s) for s in summary_texts]), sum([len(t) for t in trans_texts]), trans_ts)
    print(len(dlc.cache))
    print(dlc.translator.get_usage())
    return dlc

def post_arxiv_blocks(api, channel, df, arxiv_tweets_df, dlc, max_summary):
  def strip(s, l):
    return s[:l-3] + '...' if len(s) > l else s
  text = f'Top {len(df)} most popular arXiv papers in the last 7 days'
  blocks = [{'type': 'header', 'text': {'type': 'plain_text', 'text': text}}]
  api.chat_postMessage(channel=channel, text=text, blocks=blocks)
  time.sleep(1)
  seg = pysbd.Segmenter(language='en', clean=False)
  one_day_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
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
      is_new = True if one_day_ago < datetime.datetime.fromisoformat(trans_ts) else False
      # assert len(summary_texts) == len(trans_texts) # this rarely happen
      if len(summary_texts) != len(trans_texts):
        print('different texts length', arxiv_id, len(summary_texts), len(trans_texts))
      translation_md = '\n\n'.join(trans_texts)
      translation_md = strip(translation_md, 3000) # must be less than 3001 characters
    is_new_md = f':new: ' if is_new else ''
    title_md = strip(title, 200)
    categories_md = ' | '.join([f'<https://arxiv.org/list/{c}/recent|{c}>' for c in [primary_category] + [c for c in categories if c != primary_category and re.match(r'\w+\.\w+$', c)]])
    stats_md = f'_*{like_count}* Likes, {retweet_count} Retweets, {quote_count} Quotes, {replay_count} Replies, {tweet_count} Tweets_'
    updated_md = dateutil.parser.isoparse(updated).strftime('%d %b %Y')
    blocks = [{'type': 'section', 'text': {'type': 'mrkdwn', 'text': f'[{i+1}/{len(df)}] {is_new_md}*{title_md}*\n{stats_md}, {categories_md}, {updated_md}\n{first_summary}'}}]
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
    tw = arxiv_tweets_df[arxiv_tweets_df['arxiv_id'] == arxiv_id].sort_values(by=['like_count', 'retweet_count', 'quote_count', 'reply_count'], ascending=False)
    post_tweets_blocks(api, channel, ts, tw.head(5))
    print(f'[{i+1}/{len(df)}]')

def post_tweets_blocks(api, channel, ts, df):
  for i, (tweet_id, expanded_text, created_at, username, name, like_count, retweet_count, quote_count, replay_count) in enumerate(zip(df['id'], df['expanded_text'], df['created_at'], df['username'], df['name'], df['like_count'], df['retweet_count'], df['quote_count'], df['reply_count'])):
    blocks = []
    stats_md = f'_*{like_count}* Likes, {retweet_count} Retweets, {quote_count} Quotes, {replay_count} Replies_'
    created_at_md = dateutil.parser.isoparse(created_at).strftime('%d %b')
    url_md = f'<https://twitter.com/{username}/status/{tweet_id}|{created_at_md}>'
    blocks = [{'type': 'section', 'text': {'type': 'mrkdwn', 'text': f'[{i+1}/{len(df)}] {stats_md}, {url_md}\n'}}]
    response = api.chat_postMessage(channel=channel, text=url_md, thread_ts=ts, blocks=blocks)
    time.sleep(1)

def main():
  query = '"arxiv.org" -is:retweet'
  deepl_target_lang = 'JA'
  tweepy_api = tweepy.Client(bearer_token=os.getenv('TWITTER_BEARER_TOKEN'), wait_on_rate_limit=True)
  tweets_raw = search_recent_tweets(tweepy_api, query, since_id=None, page_limit=int(os.getenv('SEARCH_PAGE_LIMIT')))  # type: ignore
  print(len(tweets_raw['data']), len(tweets_raw['includes']['users']), tweets_raw['meta'])
  tweets_parsed = parse_tweets(tweets_raw)
  print(len(tweets_parsed['tweets']), len(tweets_parsed['users']), tweets_parsed['meta'].values[0])
  arxiv_stats = parse_arxiv(tweets_parsed['tweets'], tweets_parsed['users'], tweets_parsed['urls'])
  print(len(arxiv_stats['arxiv_stats']), len(arxiv_stats['arxiv_ids']), len(arxiv_stats['arxiv_tweets']))
  arxiv_stats_df = arxiv_stats['arxiv_stats']
  arxiv_tweets_df = arxiv_stats['arxiv_tweets']
  arxiv_ids = arxiv_stats['arxiv_stats']['arxiv_id'].tolist()
  arxiv_results = search_arxiv(arxiv_ids)
  arxiv_results_df = pd.json_normalize(arxiv_results)
  arxiv_df = pd.merge(arxiv_stats_df, arxiv_results_df, on='arxiv_id')
  dlc = deeplcache.DeepLCache(deepl.Translator(os.getenv('DEEPL_AUTH_KEY')))  # type: ignore
  gcs_bucket = storage.Client().bucket(os.getenv('GCS_BUCKET_NAME'))
  try:
    dlc.load_from_gcs(gcs_bucket, 'deepl_cache.json.gz')
  except Exception as e:
    print(e)
  notify_top_n = int(os.getenv('NOTIFY_TOP_N'))  # type: ignore
  dlc = translate_arxiv(dlc, arxiv_stats, arxiv_results, deepl_target_lang, notify_top_n, 2000) # TODO
  try:
    dlc.save_to_gcs(gcs_bucket, 'deepl_cache.json.gz')
  except Exception as e:
    print(e)
  slack_api = WebClient(os.getenv('SLACK_BOT_TOKEN'))
  post_arxiv_blocks(slack_api, os.getenv('SLACK_CHANNEL'), arxiv_df.head(notify_top_n), arxiv_tweets_df, dlc, 2000) # TODO

if __name__ == '__main__':
  main()
