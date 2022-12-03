from math import inf
import os

import tweepy


def get_my_user_id(api_v2):
  return api_v2.get_me().data.id

def get_oldest_tweet_ids(api_v2, user_id, max_results=100):
  oldest_tweets = []
  total_count = 0
  for response in tweepy.Paginator(api_v2.get_users_tweets, id=user_id, max_results=100, limit=inf, user_auth=True):
    total_count += response.meta['result_count']  # type: ignore
    for tweet in response.data:  # type: ignore
      oldest_tweets.append(tweet.id)
    oldest_tweets = oldest_tweets[-max_results:]
    assert len(oldest_tweets) <= max_results
  oldest_tweets.reverse()
  return oldest_tweets, total_count

def delete_all_tweets(api_v2, user_id):
  '''
  https://developer.twitter.com/en/docs/twitter-api/tweets/manage-tweets/api-reference/delete-tweets-id
  User rate limit (User context): 50 requests per 15-minute window per each authenticated user
  '''

  delete_count = 0
  try:
    while True:
      print('Getting oldest tweets...')
      tweet_ids, total_count = get_oldest_tweet_ids(api_v2, user_id, max_results=50)
      print('Getting oldest tweets...done')
      print(f'There are {total_count} tweets. Got oldest {len(tweet_ids)} tweets.')
      if len(tweet_ids) == 0:
        break
      print(f'It might take {(total_count // 50 + 1) * 15} minutes to delete all of the tweets because of rate limit (50 requests per 15-minute).')
      for tweet_id in tweet_ids:
        print(f'Deleting a tweet (id: {tweet_id})...', flush=True)
        response = api_v2.delete_tweet(tweet_id, user_auth=True)
        if response and response.data and 'deleted' in response.data and response.data['deleted'] == True:
          delete_count += 1
          print(f'Deleting a tweet (id: {tweet_id})...done')
        else:
          print(f'Error: {response}')
  finally:
    print(f'Deleted {delete_count} tweets.')

  return delete_count

def main():
  api_v2 = tweepy.Client(
    bearer_token=os.getenv('TWITTER_BEARER_TOKEN'),
    consumer_key=os.getenv('TWITTER_API_KEY'),
    consumer_secret=os.getenv('TWITTER_API_KEY_SECRET'),
    access_token=os.getenv('TWITTER_ACCESS_TOKEN'),
    access_token_secret=os.getenv('TWITTER_ACCESS_TOKEN_SECRET'),
    wait_on_rate_limit=True)

  user_id = get_my_user_id(api_v2)

  delete_all_tweets(api_v2, user_id)


if __name__ == '__main__':
  main()
