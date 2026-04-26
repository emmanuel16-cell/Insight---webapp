import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';
import 'api_service.dart';
import 'login_page.dart';
import 'scanner_page.dart';
import 'subjects_page.dart';
import 'logs_page.dart';
import 'profile_page.dart';
import 'package:intl/intl.dart';

class DashboardPage extends StatefulWidget {
  const DashboardPage({super.key});

  @override
  State<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends State<DashboardPage> {
  int _selectedIndex = 0;
  Map<String, dynamic>? _dashboardData;
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _fetchDashboardData();
  }

  Future<void> _fetchDashboardData() async {
    try {
      final response = await ApiService().getStudentDashboard();
      if (response.statusCode == 200) {
        setState(() {
          _dashboardData = response.data as Map<String, dynamic>?;
          _isLoading = false;
        });
      }
    } catch (e) {
      setState(() {
        _isLoading = false;
      });
    }
  }

  void _onItemTapped(int index) {
    setState(() {
      _selectedIndex = index;
    });
  }

  Future<void> _handleLogout() async {
    try {
      await ApiService().logout();
      if (mounted) {
        Navigator.of(context).pushReplacement(
          MaterialPageRoute(builder: (context) => const LoginPage()),
        );
      }
    } catch (e) {
      // Handle error
    }
  }

  @override
  Widget build(BuildContext context) {
    final List<Widget> pages = [
      _buildOverview(),
      const LogsPage(),
      const SubjectsPage(),
      const ProfilePage(),
    ];

    return Scaffold(
      appBar: AppBar(
        title: Text(
          _selectedIndex == 0 ? 'Dashboard' : 
          _selectedIndex == 1 ? 'Logs' :
          _selectedIndex == 2 ? 'Subjects' : 'Profile',
          style: const TextStyle(fontWeight: FontWeight.bold),
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.qr_code_scanner),
            onPressed: () {
              Navigator.of(context).push(
                MaterialPageRoute(builder: (context) => const ScannerPage()),
              );
            },
          ),
          IconButton(
            icon: const Icon(Icons.logout),
            onPressed: _handleLogout,
          ),
        ],
      ),
      body: pages[_selectedIndex],
      bottomNavigationBar: BottomNavigationBar(
        items: const <BottomNavigationBarItem>[
          BottomNavigationBarItem(icon: Icon(Icons.dashboard), label: 'Overview'),
          BottomNavigationBarItem(icon: Icon(Icons.history), label: 'Logs'),
          BottomNavigationBarItem(icon: Icon(Icons.book), label: 'Subjects'),
          BottomNavigationBarItem(icon: Icon(Icons.person), label: 'Profile'),
        ],
        currentIndex: _selectedIndex,
        selectedItemColor: const Color(0xFF2EC4B6),
        unselectedItemColor: Colors.white70,
        backgroundColor: const Color(0xFF023047),
        onTap: _onItemTapped,
        type: BottomNavigationBarType.fixed,
      ),
    );
  }

  Widget _buildOverview() {
    if (_isLoading) {
      return const Center(child: CircularProgressIndicator());
    }

    final Map<String, dynamic> stats = Map<String, dynamic>.from(_dashboardData?['statistics'] ?? {});
    final List<dynamic> recentLogs = List<dynamic>.from(_dashboardData?['recent_logs'] ?? []);

    return RefreshIndicator(
      onRefresh: _fetchDashboardData,
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _buildStatGrid(stats),
            const SizedBox(height: 24),
            const Text(
              'Attendance Trend (Last 7 Days)',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 16),
            _buildAttendanceChart(),
            const SizedBox(height: 24),
            const Text(
              'Subject Comparison',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 16),
            _buildComparisonList(),
            const SizedBox(height: 24),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text(
                  'Recent Logs',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                ),
                TextButton(
                  onPressed: () => _onItemTapped(1),
                  child: const Text('View All'),
                ),
              ],
            ),
            _buildRecentLogsList(recentLogs),
          ],
        ),
      ),
    );
  }

  Widget _buildStatGrid(Map<String, dynamic> stats) {
    return GridView.count(
      crossAxisCount: 2,
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      crossAxisSpacing: 12,
      mainAxisSpacing: 12,
      childAspectRatio: 2.2,
      children: [
        _buildStatCard(
          'Avg Attendance',
          '${stats['overall_attendance_percentage'] ?? 0}%',
          const Color(0xFF2EC4B6),
          Icons.people,
        ),
        _buildStatCard(
          'Classes Held',
          '${stats['total_sessions_held'] ?? 0}',
          const Color(0xFF219EBC),
          Icons.school,
        ),
        _buildStatCard(
          'Attended',
          '${stats['total_sessions_attended'] ?? 0}',
          const Color(0xFFFFB703),
          Icons.check_circle,
        ),
        _buildStatCard(
          'Missed',
          '${stats['total_sessions_missed'] ?? 0}',
          const Color(0xFFFB8500),
          Icons.cancel,
        ),
      ],
    );
  }

  Widget _buildStatCard(String title, String value, Color color, IconData icon) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: color,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        children: [
          Icon(icon, color: Colors.white.withOpacity(0.8), size: 30),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(
                  title,
                  style: const TextStyle(color: Colors.white, fontSize: 11),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                Text(
                  value,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 20,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildAttendanceChart() {
    final chartData = _dashboardData?['chart_data'] as List? ?? [];
    if (chartData.isEmpty) {
      return Container(
        height: 200,
        decoration: BoxDecoration(
          color: Colors.grey[100],
          borderRadius: BorderRadius.circular(12),
        ),
        child: const Center(child: Text('No data for last 7 days')),
      );
    }

    final spots = chartData.asMap().entries.map((e) {
      return FlSpot(e.key.toDouble(), (e.value['me_rate'] ?? 0).toDouble());
    }).toList();

    return Container(
      height: 220,
      padding: const EdgeInsets.fromLTRB(8, 24, 24, 8),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.05),
            spreadRadius: 2,
            blurRadius: 10,
          ),
        ],
      ),
      child: LineChart(
        LineChartData(
          gridData: FlGridData(
            show: true,
            drawVerticalLine: false,
            getDrawingHorizontalLine: (value) => const FlLine(
              color: Color(0xFFEEEEEE),
              strokeWidth: 1,
            ),
          ),
          titlesData: FlTitlesData(
            rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
            topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
            bottomTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                getTitlesWidget: (value, meta) {
                  int idx = value.toInt();
                  if (idx < 0 || idx >= chartData.length) return const SizedBox();
                  String dateStr = chartData[idx]['date'];
                  DateTime date = DateTime.parse(dateStr);
                  return Padding(
                    padding: const EdgeInsets.only(top: 8.0),
                    child: Text(
                      DateFormat('E').format(date),
                      style: const TextStyle(fontSize: 10, color: Colors.grey),
                    ),
                  );
                },
              ),
            ),
            leftTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                reservedSize: 35,
                getTitlesWidget: (value, meta) => Text(
                  '${value.toInt()}%',
                  style: const TextStyle(fontSize: 10, color: Colors.grey),
                ),
              ),
            ),
          ),
          borderData: FlBorderData(show: false),
          minY: 0,
          maxY: 100,
          lineBarsData: [
            LineChartBarData(
              spots: spots,
              isCurved: true,
              color: const Color(0xFF2EC4B6),
              barWidth: 4,
              isStrokeCapRound: true,
              dotData: const FlDotData(show: true),
              belowBarData: BarAreaData(
                show: true,
                color: const Color(0xFF2EC4B6).withOpacity(0.1),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildComparisonList() {
    final courses = _dashboardData?['enrolled_courses'] as List? ?? [];
    if (courses.isEmpty) return const Text('No subjects enrolled');

    return Column(
      children: courses.map((course) {
        double pct = 0;
        if (course['total_sessions'] > 0) {
          pct = (course['present_count'] / course['total_sessions']) * 100;
        }

        return Padding(
          padding: const EdgeInsets.only(bottom: 16.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                    course['course_name'] ?? course['course_code'],
                    style: const TextStyle(fontWeight: FontWeight.w500),
                  ),
                  Text(
                    '${pct.toStringAsFixed(1)}%',
                    style: TextStyle(
                      color: pct < 75 ? Colors.orange : const Color(0xFF2EC4B6),
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              ClipRRect(
                borderRadius: BorderRadius.circular(4),
                child: LinearProgressIndicator(
                  value: pct / 100,
                  backgroundColor: Colors.grey[200],
                  color: pct < 75 ? Colors.orange : const Color(0xFF2EC4B6),
                  minHeight: 10,
                ),
              ),
            ],
          ),
        );
      }).toList(),
    );
  }

  Widget _buildRecentLogsList(List logs) {
    if (logs.isEmpty) return const Center(child: Padding(
      padding: EdgeInsets.all(20.0),
      child: Text('No recent biometric logs'),
    ));

    return ListView.builder(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      itemCount: logs.length,
      itemBuilder: (context, index) {
        final log = logs[index];
        final timeStr = log['time'] != null ? DateFormat('hh:mm a').format(DateTime.parse(log['time'])) : '—';
        final dateStr = log['date'] != null ? DateFormat('MMM dd, yyyy').format(DateTime.parse(log['date'])) : '—';
        
        final status = (log['status'] ?? '—').toString().toLowerCase();
        final isSuccess = status == 'entry' || status == 'exit' || status == 'present' || status == 'late' || status == 'attended';
        final isOutOfRange = status == 'out_of_range';

        return ListTile(
          contentPadding: EdgeInsets.zero,
          leading: CircleAvatar(
            backgroundColor: const Color(0xFF2EC4B6).withOpacity(0.1),
            child: Icon(
              log['type'] == 'Gate' ? Icons.door_front_door : 
              log['type'] == 'Subject' ? Icons.book : Icons.info_outline, 
              color: const Color(0xFF2EC4B6),
              size: 20,
            ),
          ),
          title: Text(log['type'] ?? 'Log', style: const TextStyle(fontWeight: FontWeight.bold)),
          subtitle: Text('$dateStr • $timeStr\n${log['name'] ?? ''}', style: const TextStyle(fontSize: 12)),
          isThreeLine: true,
          trailing: Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            decoration: BoxDecoration(
              color: isSuccess ? Colors.green[50] : (isOutOfRange ? Colors.orange[50] : Colors.red[50]),
              borderRadius: BorderRadius.circular(4),
            ),
            child: Text(
              status.replaceAll('_', ' ').toUpperCase(),
              style: TextStyle(
                color: isSuccess ? Colors.green : (isOutOfRange ? Colors.orange : Colors.red),
                fontSize: 10,
                fontWeight: FontWeight.bold,
              ),
            ),
          ),
        );
      },
    );
  }
}
