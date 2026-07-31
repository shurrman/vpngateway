import 'package:dio/dio.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../config.dart';

class ApiClient {
  late Dio _dio;
  String _baseUrl = defaultApiUrl;

  ApiClient() {
    _dio = Dio(BaseOptions(connectTimeout: const Duration(seconds: 10), receiveTimeout: const Duration(seconds: 30)));
    _loadBaseUrl();
  }

  /// Use the operating system trust store. Install the gateway CA on
  /// the device, or terminate HTTPS with a publicly trusted certificate.
  Future<void> initSsl() async {
  }

  Future<void> _loadBaseUrl() async {
    final prefs = await SharedPreferences.getInstance();
    _baseUrl = prefs.getString('api_url') ?? defaultApiUrl;
  }

  Future<void> setBaseUrl(String url) async {
    _baseUrl = url;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('api_url', url);
  }

  String get baseUrl => _baseUrl;

  Future<Map<String, dynamic>> _request(String method, String path, {Map<String, dynamic>? body}) async {
    await _loadBaseUrl();
    final url = '$_baseUrl$apiPrefix$path';
    Response resp;
    switch (method) {
      case 'GET': resp = await _dio.get(url); break;
      case 'POST': resp = await _dio.post(url, data: body); break;
      case 'PUT': resp = await _dio.put(url, data: body); break;
      case 'DELETE': resp = await _dio.delete(url, data: body); break;
      default: throw Exception('Unknown method: $method');
    }
    final data = resp.data as Map<String, dynamic>;
    if (data['status'] == 'error') throw Exception(data['error'] ?? 'Unknown error');
    return data;
  }

  Future<dynamic> get(String path) async => (await _request('GET', path))['data'];
  Future<Map<String, dynamic>> getWithLog(String path) async => await _request('GET', path);
  Future<Map<String, dynamic>> post(String path, {Map<String, dynamic>? body}) async => await _request('POST', path, body: body);
  Future<Map<String, dynamic>> put(String path, {Map<String, dynamic>? body}) async => await _request('PUT', path, body: body);
  Future<Map<String, dynamic>> del(String path, {Map<String, dynamic>? body}) async => await _request('DELETE', path, body: body);

  Future<bool> testConnection() async {
    try {
      await _loadBaseUrl();
      final url = '$_baseUrl$apiPrefix/health';
      final resp = await _dio.get(url);
      _apiVersion = resp.data['version'] != null ? 'v${resp.data['version']}' : null;
      return resp.data['status'] == 'ok';
    } catch (e) {
      _lastError = e.toString();
      return false;
    }
  }

  String? _lastError;
  String? get lastError => _lastError;

  String? _apiVersion;
  String? get apiVersion => _apiVersion;
}

final api = ApiClient();
