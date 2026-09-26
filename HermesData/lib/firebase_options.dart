import 'package:firebase_core/firebase_core.dart' show FirebaseOptions;
import 'package:flutter/foundation.dart' show defaultTargetPlatform, kIsWeb, TargetPlatform;

class DefaultFirebaseOptions {
  static FirebaseOptions get currentPlatform {
    return web;
  }

  static const FirebaseOptions web = FirebaseOptions(
    apiKey: 'AIzaSyBRtLkofS3VwBkrE8GpbKUaYimLTldDTj8',
    authDomain: 'bafa-inventory.firebaseapp.com',
    projectId: 'bafa-inventory',
    storageBucket: 'bafa-inventory.firebasestorage.app',
    messagingSenderId: '970143880702',
    appId: '1:970143880702:web:ea7aebf1af5f37deb69caf',
    measurementId: 'G-MNPS9HC87D',
  );
}
