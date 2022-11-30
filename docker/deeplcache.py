import datetime
import gzip
import json

class DeepLCache:
  def __init__(self, translator):
    self.translator = translator
    self.cache = {}

  def clear_cache(self):
    # TODO: specify datetime
    self.cache = {}

  def __repr__(self):
    return repr(self.cache) # TODO

  def load(self, filename):
    with gzip.open(filename, 'rt', encoding='UTF-8') as f:
      self.cache = json.load(f)

  def save(self, filename):
    with gzip.open(filename, 'wt', encoding='UTF-8') as f:
      json.dump(self.cache, f)

  def load_from_s3(self, s3_bucket, filename):
    s3_bucket.download_file(filename, filename)
    self.load(filename)

  def save_to_s3(self, s3_bucket, filename):
    self.save(filename)
    s3_bucket.upload_file(filename, filename)

  def load_from_gcs(self, gcs_bucket, filename):
    gcs_bucket.blob(filename).download_to_filename(filename)
    self.load(filename)

  def save_to_gcs(self, gcs_bucket, filename):
    self.save(filename)
    gcs_bucket.blob(filename).upload_from_filename(filename)

  def get(self, key, default=None):
    return self.cache.get(key, default)

  def translate_text(self, text, target_lang, key):
    trans = self.get(key, None)
    if trans is not None:
      return trans
    result = self.translator.translate_text(text=text, target_lang=target_lang)
    trans_texts = [r.text for r in result] if type(text) is list else result.text
    trans_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    trans = [trans_texts, trans_ts]
    self.cache[key] = trans
    return trans
