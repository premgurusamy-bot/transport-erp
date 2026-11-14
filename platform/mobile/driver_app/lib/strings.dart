// Tamil / English strings for the Driver App.
class S {
  static String lang = 'en';
  static void toggle() => lang = lang == 'en' ? 'ta' : 'en';
  static const Map<String, Map<String, String>> _d = {
    'app': {'en': 'GRL Driver', 'ta': 'GRL ஓட்டுநர்'},
    'signin': {'en': 'Sign in', 'ta': 'உள்நுழை'},
    'myTrips': {'en': 'My trips', 'ta': 'என் பயணங்கள்'},
    'park': {
      'en': 'Park safely before using the app. Never use the phone while driving.',
      'ta': 'வாகனத்தை பாதுகாப்பாக நிறுத்திய பின் மட்டுமே பயன்படுத்தவும். ஓட்டும்போது கைபேசியை பயன்படுத்தாதீர்கள்.'
    },
    'sos': {'en': 'SOS / Emergency', 'ta': 'அவசர உதவி'},
  };
  static String t(String k) => _d[k]?[lang] ?? _d[k]?['en'] ?? k;
}
