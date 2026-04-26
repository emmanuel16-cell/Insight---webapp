import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'api_service_platform.dart';

class ApiService {
  static final ApiService _instance = ApiService._internal();
  factory ApiService() => _instance;

  late Dio dio;
  
  // Default fallback URL
  String baseUrl = getDefaultBaseUrl(); 

  ApiService._internal() {
    dio = Dio(BaseOptions(
      baseUrl: baseUrl,
      connectTimeout: const Duration(seconds: 5),
      receiveTimeout: const Duration(seconds: 5),
      headers: {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
      },
    ));
    
    _init();
  }

  Future<void> _init() async {
    await _loadSavedBaseUrl();
    await configureDioForPlatform(dio);
    _initInterceptors();
    
    // Start discovery if connection fails
    _tryDiscovery();
  }

  Future<void> _loadSavedBaseUrl() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final savedUrl = prefs.getString('server_base_url');
      if (savedUrl != null) {
        setBaseUrl(savedUrl);
        if (kDebugMode) print("🏠 Loaded saved server URL: $savedUrl");
      }
    } catch (e) {
      if (kDebugMode) print("⚠️ Failed to load saved URL: $e");
    }
  }

  Future<void> _tryDiscovery() async {
    // Try a quick ping to see if current URL works
    try {
      await dio.get('/api/auth/me'); // Simple health check
      if (kDebugMode) print("✅ Connection to $baseUrl is active.");
      return;
    } catch (e) {
      if (kDebugMode) print("🔍 Connection to $baseUrl failed, starting discovery...");
      discoverServerForPlatform(
        currentBaseUrl: baseUrl,
        onUrlDiscovered: (newUrl) {
          if (kDebugMode) print("✨ Discovered server at: $newUrl");
          setBaseUrl(newUrl);
          _saveBaseUrl(newUrl);
        },
      );
    }
  }

  Future<void> _saveBaseUrl(String url) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('server_base_url', url);
  }

  void _initInterceptors() {
    dio.interceptors.add(InterceptorsWrapper(
      onResponse: (response, handler) {
        // Automatically convert Dio's LinkedMap to Map<String, dynamic>
        response.data = convertDioResponse(response.data);
        return handler.next(response);
      },
    ));
  }

  void setBaseUrl(String url) {
    baseUrl = url;
    dio.options.baseUrl = url;
  }

  // Auth
  Future<Response> login(String email, String password) async {
    return await dio.post('/api/auth/login', data: {
      'email': email,
      'password': password,
    });
  }

  Future<Response> logout() async {
    return await dio.post('/api/auth/logout');
  }

  Future<Response> getMe() async {
    return await dio.get('/api/auth/me');
  }

  // Dashboard / Overview
  Future<Response> getStudentDashboard() async {
    return await dio.get('/api/dashboard/student');
  }

  // Profile
  Future<Response> getProfile() async {
    return await dio.get('/api/user/profile');
  }

  Future<Response> updateProfile(Map<String, dynamic> data) async {
    return await dio.put('/api/user/profile', data: data);
  }

  Future<Response> changePassword(String currentPwd, String newPwd, String confirmPwd) async {
    return await dio.post('/api/user/change-password', data: {
      'current_password': currentPwd,
      'new_password': newPwd,
      'confirm_password': confirmPwd,
    });
  }

  // Subjects
  Future<Response> getMySubjects() async {
    return await dio.get('/api/student/subjects');
  }

  Future<Response> getMyEnrollments() async {
    return await dio.get('/api/student/enrollments');
  }

  Future<Response> enrollSubject(String joinCode) async {
    return await dio.post('/api/student/subjects/enroll', data: {
      'join_code': joinCode,
    });
  }

  // Logs
  Future<Response> getGateLogs({int limit = 50, int offset = 0}) async {
    return await dio.get('/api/gate-logs', queryParameters: {
      'limit': limit,
      'offset': offset,
    });
  }

  Future<Response> getSubjectLogs() async {
    return await dio.get('/api/attendance/my-attendance');
  }

  // Attendance Scanning
  Future<Response> markAttendance(String code, double? lat, double? lon) async {
    return await dio.post('/api/scan/manual', data: {
      'code': code,
      'latitude': lat,
      'longitude': lon,
    });
  }

  // Alias for manual scan, both use the same endpoint
  Future<Response> manualScan(String code, double? lat, double? lon) => 
      markAttendance(code, lat, lon);

  // Helper function to convert Dio LinkedMap/LinkedList to regular Dart types
  static dynamic convertDioResponse(dynamic data) {
    if (data == null) return null;
    if (data is Map) {
      return Map<String, dynamic>.from(
        data.map((key, value) => MapEntry(key.toString(), convertDioResponse(value)))
      );
    }
    if (data is List) {
      return data.map((item) => convertDioResponse(item)).toList();
    }
    return data;
  }
}
