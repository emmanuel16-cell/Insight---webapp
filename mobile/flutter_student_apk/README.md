# InSight Student Mobile App (Flutter)

This is a Flutter-based mobile application for students in the InSight system.

## Features
- Dedicated Mobile Login
- Attendance Stats Dashboard
- Biometric Logs (Gate, Subject, Event)
- Subject Management & Enrollment
- Event List
- QR Code Scanner for Attendance
- Responsive Mobile UI

## Setup Instructions

1.  **Install Flutter SDK**: 
    - Download and install Flutter from [flutter.dev](https://docs.flutter.dev/get-started/install).
    - Ensure `flutter` is in your system PATH.

2.  **Initialize Project**:
    - Open a terminal in this folder.
    - Run `flutter create .` to generate the necessary platform-specific files (android, ios, web).

3.  **Install Dependencies**:
    - Run `flutter pub get`.

4.  **Configure API URL**:
    - Open `lib/api_service.dart`.
    - Update `baseUrl` to match your backend server's IP address (e.g., `http://192.168.1.100:8000`).

## Testing in the Browser (No Android Studio Required)

To test the app in your browser:
1.  Run the following command:
    ```bash
    flutter run -d chrome
    ```
2.  The app will open in Chrome. You can use the **Device Toolbar** (F12 -> Ctrl+Shift+M) to simulate different mobile screen sizes.

## Building the APK

Once you are ready to create the Android APK:
1.  Run:
    ```bash
    flutter build apk --release
    ```
2.  The resulting APK will be located at `build/app/outputs/flutter-apk/app-release.apk`.
