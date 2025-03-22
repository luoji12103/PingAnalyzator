import re
import pandas as pd
from datetime import datetime
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import sys

def read_ping_data(file_path):
    """Read ping data from the text file and extract host address"""
    ping_data = []
    host_address = None
    
    with open(file_path, 'r') as file:
        # Get host address from first line
        first_line = file.readline().strip()
        host_match = re.search(r'Target Host=(\d+\.\d+\.\d+\.\d+)', first_line)
        if host_match:
            host_address = host_match.group(1)
        
        # Read and parse the remaining lines
        for line in file:
            line = line.strip()
            date_time_match = re.match(r'(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})', line)
            if date_time_match:
                try:
                    # Parse timestamp
                    timestamp_str = date_time_match.group(1)
                    timestamp = datetime.strptime(timestamp_str, '%Y/%m/%d %H:%M:%S')
                    
                    # Determine if successful ping or packet loss
                    if "Reply from" in line:
                        result = "success"
                        time_match = re.search(r'time=(\d+)ms', line)
                        response_time = int(time_match.group(1)) if time_match else None
                    else:
                        result = "failure"
                        response_time = None
                    
                    ping_data.append({
                        'timestamp': timestamp,
                        'hour': timestamp.replace(minute=0, second=0),
                        'result': result,
                        'response_time': response_time
                    })
                except Exception as e:
                    print(f"Error parsing line: {line}, Error: {e}")
    
    return host_address, ping_data

def analyze_ping_data(host_address, ping_data, disconnect_threshold=3):
    """Analyze ping data for packet loss and disconnections"""
    # Convert to DataFrame for analysis
    df = pd.DataFrame(ping_data)
    
    # Get start time, end time and duration of the ping data
    start_time = df['timestamp'].min() if not df.empty else None
    end_time = df['timestamp'].max() if not df.empty else None
    duration = end_time - start_time if start_time and end_time else None
    
    # Calculate overall packet loss rate
    total_pings = len(df)
    successful_pings = len(df[df['result'] == 'success'])
    failed_pings = total_pings - successful_pings
    overall_packet_loss_rate = (failed_pings / total_pings) * 100 if total_pings > 0 else 0
    
    # Calculate hourly statistics
    hourly_stats = df.groupby('hour').agg(
        total_pings=('result', 'count'),
        successful_pings=('result', lambda x: (x == 'success').sum())
    )
    
    hourly_stats['packet_loss_count'] = hourly_stats['total_pings'] - hourly_stats['successful_pings']
    hourly_stats['packet_loss_rate'] = (hourly_stats['packet_loss_count'] / hourly_stats['total_pings']) * 100
    
    # Detect disconnections (consecutive failures)
    disconnections = []
    failure_count = 0
    current_disconnection = None
    
    for i, row in df.iterrows():
        if row['result'] == 'failure':
            failure_count += 1
            if failure_count == disconnect_threshold:
                # Start of a new disconnection
                start_idx = i - disconnect_threshold + 1
                current_disconnection = {
                    'start_time': df.iloc[start_idx]['timestamp'],
                    'count': disconnect_threshold
                }
            elif failure_count > disconnect_threshold and current_disconnection is not None:
                # Continuation of current disconnection
                current_disconnection['count'] += 1
        else:
            if current_disconnection is not None:
                # End of current disconnection
                current_disconnection['end_time'] = row['timestamp']
                current_disconnection['duration'] = (current_disconnection['end_time'] - current_disconnection['start_time']).total_seconds()
                disconnections.append(current_disconnection)
                current_disconnection = None
            failure_count = 0
    
    # Check if file ends during a disconnection
    if current_disconnection is not None:
        current_disconnection['end_time'] = df.iloc[-1]['timestamp']
        current_disconnection['duration'] = (current_disconnection['end_time'] - current_disconnection['start_time']).total_seconds()
        disconnections.append(current_disconnection)
    
    # Calculate hourly disconnection counts
    hourly_disconnection_counts = {}
    for disc in disconnections:
        hour = disc['start_time'].replace(minute=0, second=0, microsecond=0)
        if hour in hourly_disconnection_counts:
            hourly_disconnection_counts[hour] += 1
        else:
            hourly_disconnection_counts[hour] = 1
    
    # Create hourly disconnection dataframe
    hourly_disconnection_df = pd.DataFrame(
        [{'hour': hour, 'count': count} for hour, count in hourly_disconnection_counts.items()]
    )
    if not hourly_disconnection_df.empty:
        hourly_disconnection_df.set_index('hour', inplace=True)
    
    # Make sure all hours in data range have an entry
    if not df.empty:
        all_hours = pd.date_range(
            start=df['hour'].min(), 
            end=df['hour'].max(), 
            freq='H'
        )
        hourly_disconnection_df = hourly_disconnection_df.reindex(all_hours, fill_value=0)
    
    return hourly_stats, disconnections, overall_packet_loss_rate, start_time, end_time, duration, hourly_disconnection_df

def print_analysis_results(host_address, hourly_stats, disconnections, overall_packet_loss_rate, 
                          start_time, end_time, duration, avg_disc_duration=None, 
                          max_disc_duration=None, min_disc_duration=None):
    """打印分析结果"""
    print(f"===== Ping Data Analysis for {host_address} =====\n")
    
    # 打印ping数据时间范围
    print("Analysis Time Range:")
    print(f"Start Time: {start_time.strftime('%Y/%m/%d %H:%M:%S')}")
    print(f"End Time: {end_time.strftime('%Y/%m/%d %H:%M:%S')}")
    print(f"Duration: {duration}")
    print()
    
    # 打印总体丢包率
    print(f"Overall Packet Loss Rate: {overall_packet_loss_rate:.2f}%\n")
    
    # 打印每小时丢包率
    print("Hourly Packet Loss Rates:")
    print("-------------------------")
    for hour, row in hourly_stats.iterrows():
        print(f"{hour.strftime('%Y/%m/%d %H:00')}: {row['packet_loss_rate']:.2f}% ({row['packet_loss_count']} of {row['total_pings']} pings)")
    
    # 打印断联统计
    if disconnections:
        # 打印断联统计摘要
        print("\nDisconnection Summary:")
        print("---------------------")
        print(f"Total disconnections: {len(disconnections)}")
        
        # 打印断联时间统计
        if avg_disc_duration is not None:
            print(f"Average disconnection duration: {avg_disc_duration:.2f} seconds")
        
        if max_disc_duration is not None:
            max_disc_index = next((i + 1 for i, d in enumerate(disconnections) if d['duration'] == max_disc_duration), None)
            print(f"Maximum disconnection duration: {max_disc_duration:.2f} seconds (Disconnection #{max_disc_index})")
        
        if min_disc_duration is not None:
            min_disc_index = next((i + 1 for i, d in enumerate(disconnections) if d['duration'] == min_disc_duration), None)
            print(f"Minimum disconnection duration: {min_disc_duration:.2f} seconds (Disconnection #{min_disc_index})")
            
        # 计算每小时平均断联次数
        avg_count = sum(d['count'] for d in disconnections) / len(disconnections)
        print(f"Average packet loss per disconnection: {avg_count:.2f}")
        
        # 计算每小时平均断联次数
        hours_count = len(hourly_stats)
        if hours_count > 0:
            avg_disconnections_per_hour = len(disconnections) / hours_count
            print(f"Average disconnections per hour: {avg_disconnections_per_hour:.2f}")
        
        # 打印断联事件
        print("\nDisconnection Events:")
        print("--------------------")
        for i, disc in enumerate(disconnections, 1):
            print(f"Disconnection #{i}:")
            print(f"  Start time: {disc['start_time'].strftime('%Y/%m/%d %H:%M:%S')}")
            print(f"  End time:   {disc['end_time'].strftime('%Y/%m/%d %H:%M:%S')}")
            print(f"  Duration:   {disc['duration']:.2f} seconds")
            print(f"  Packet loss count: {disc['count']}")
    else:
        print("\nNo disconnection events detected.")



def calculate_disconnection_stats(disconnections):
    """计算断联时间的统计信息：平均值、最大值和最小值"""
    if not disconnections:
        return None, None, None
    
    durations = [d['duration'] for d in disconnections]
    avg_duration = sum(durations) / len(durations)
    max_duration = max(durations)
    min_duration = min(durations)
    
    return avg_duration, max_duration, min_duration

def save_output_to_log(log_file_path):
    """设置同时输出到控制台和日志文件"""
    import sys
    from datetime import datetime
    
    class Logger:
        def __init__(self, filename):
            self.terminal = sys.stdout
            self.log = open(filename, 'w', encoding='utf-8')
            # 在日志开头写入时间戳
            self.log.write(f"=== Analysis started at {datetime.now().strftime('%Y/%m/%d %H:%M:%S')} ===\n\n")
            
        def write(self, message):
            self.terminal.write(message)
            self.log.write(message)
            
        def flush(self):
            self.terminal.flush()
            self.log.flush()
            
        def close(self):
            self.log.close()
    
    logger = Logger(log_file_path)
    sys.stdout = logger
    return logger


def plot_disconnection_duration_vs_count(disconnections):
    """绘制断联时长与断联次数关系图"""
    if not disconnections:
        print("没有断联数据可以绘图")
        return
    
    # 提取持续时间
    durations = [d['duration'] for d in disconnections]
    
    # 计算每个持续时间出现的次数
    duration_counts = {duration: durations.count(duration) for duration in set(durations)}
    
    # 绘制图表
    plt.figure(figsize=(10, 6))
    plt.bar(duration_counts.keys(), duration_counts.values(), 
            color='blue', edgecolor='black', linewidth=1)
    plt.title('Disconnection Duration vs. Count')
    plt.xlabel('Disconnection Duration (seconds)')
    plt.ylabel('Number of Disconnections')
    plt.grid(axis='y', linestyle='--')
    plt.tight_layout()
    plt.savefig('disconnection_duration_vs_count.png')
    print("断联时长与次数图表已保存为 'disconnection_duration_vs_count.png'")


def plot_packet_loss_rate(hourly_stats):
    """Plot the hourly packet loss rate as a graph"""
    plt.figure(figsize=(12, 6))
    plt.plot(hourly_stats.index, hourly_stats['packet_loss_rate'], marker='o', linestyle='-', color='blue')
    plt.title('Hourly Packet Loss Rate')
    plt.xlabel('Hour')
    plt.ylabel('Packet Loss Rate (%)')
    plt.grid(True)
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y/%m/%d %H:%M'))
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig('hourly_packet_loss_rate.png')
    print("\nHourly packet loss rate chart saved as 'hourly_packet_loss_rate.png'")

def plot_hourly_disconnections(hourly_disconnection_df):
    """Plot the hourly disconnection counts as a bar chart"""
    plt.figure(figsize=(12, 6))
    
    # Change bar color to blue and add black edge
    plt.bar(hourly_disconnection_df.index, hourly_disconnection_df['count'], 
            color='blue', linewidth=1)
    
    plt.title('Hourly Disconnection Counts')
    plt.xlabel('Hour')
    plt.ylabel('Number of Disconnections')
    
    # Use dashed lines for horizontal grid lines
    plt.grid(axis='x', linestyle='-')
    
    # Improve date formatting
    formatter = mdates.DateFormatter('%Y/%m/%d %H:00')
    plt.gca().xaxis.set_major_formatter(formatter)
    
    # Ensure appropriate number of tick marks based on data range
    if len(hourly_disconnection_df) > 20:
        plt.gca().xaxis.set_major_locator(mdates.HourLocator(interval=4))
    else:
        plt.gca().xaxis.set_major_locator(mdates.HourLocator(interval=1))
        
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig('hourly_disconnection_counts.png')
    print("Hourly disconnection counts chart saved as 'hourly_disconnection_counts.png'")


def main():
    file_path = input("Enter the path to the ping data file: ")
    disconnect_threshold = 3  # 默认断联阈值
    
    try:
        # 设置日志输出
        log_file = "alayzation_result.log"
        logger = save_output_to_log(log_file)
        
        # 可选：自定义断联阈值
        custom_threshold = input(f"Enter the number of consecutive failures to consider as a disconnection (default: {disconnect_threshold}): ")
        if custom_threshold.strip() and custom_threshold.isdigit():
            disconnect_threshold = int(custom_threshold)
        
        # 读取和分析 ping 数据
        host_address, ping_data = read_ping_data(file_path)
        
        if not host_address:
            print("Error: Could not determine the target host address from the file.")
            logger.close()
            sys.stdout = logger.terminal
            return
        
        if not ping_data:
            print("Error: No valid ping data found in the file.")
            logger.close()
            sys.stdout = logger.terminal
            return
        
        hourly_stats, disconnections, overall_packet_loss_rate, start_time, end_time, duration, hourly_disconnection_df = analyze_ping_data(
            host_address, ping_data, disconnect_threshold
        )
        
        # 计算断联统计信息
        avg_disc_duration, max_disc_duration, min_disc_duration = calculate_disconnection_stats(disconnections)
        
        # 打印结果和生成图表
        print_analysis_results(
            host_address, hourly_stats, disconnections, overall_packet_loss_rate, 
            start_time, end_time, duration, avg_disc_duration, max_disc_duration, min_disc_duration
        )
        
        if not hourly_stats.empty:
            plot_packet_loss_rate(hourly_stats)
            plot_hourly_disconnections(hourly_disconnection_df)
            
        # 绘制断联时长与次数图表
        if disconnections:
            plot_disconnection_duration_vs_count(disconnections)
        
        # 关闭日志记录器以确保文件正确保存
        logger.close()
        # 恢复stdout
        sys.stdout = logger.terminal
        
        print(f"\n分析结果已保存到 '{log_file}'")
        
    except Exception as e:
        print(f"An error occurred: {e}")
        # 确保在发生错误时重置stdout
        if 'logger' in locals():
            sys.stdout = logger.terminal



if __name__ == "__main__":
    main()
