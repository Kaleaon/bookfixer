from calibre.utils.config import JSONConfig

prefs = JSONConfig('plugins/reddit_follower')
prefs.defaults['follows'] = []        # followed series, see core.new_follow
prefs.defaults['mode'] = 'rss'        # 'rss' (public Atom feeds) or 'api' (official API with your own credentials)
prefs.defaults['client_id'] = ''
prefs.defaults['client_secret'] = ''
prefs.defaults['username'] = ''       # your Reddit username, put in the API user agent as Reddit requires
prefs.defaults['auto_check'] = True
prefs.defaults['check_hours'] = 6.0
