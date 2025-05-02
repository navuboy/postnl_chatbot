import pandas as pd
import re

# ======================
# 📊 Prompt Templates
# ======================
INDIVIDUAL_SUGGESTIONS_TEMPLATE = [
    "How many parcels did {partner} deliver in the last quarter?",
    "What were the busiest day for {partner} between the years 2020 and 2022?",
    "Show me {partner}'s average parcel weight this year.",
    "How active was {partner} in the last 30 days?",
    "On which dates did {partner} record parcels with item count but weighing zero kg?, generate a table",
    "“What’s the trend in {partner}'s deliveries over the last 3 months?"
]

KPI_SUGGESTIONS_TEMPLATE = [
    "What is the total volume for {partner} last month?",
    "How does {partner} compare to last year in parcel volume?",
    "Show me delivery trends for {partner} over the past 6 months.",
    "Which days had the highest parcel counts for {partner}?",
    "Give me {partner}'s average parcels per active day in 2024. Generate a table if possible"
]


MULTI_INDIVIDUAL_QUESTIONS = [
    "Compare total volume this month across all selected partners.",
    "Which partner had the highest average weight per parcel this quarter?",
    "Which partner was most consistent in daily delivery activity?",
    "Compare the number of active delivery days per partner this year.",
    "Which partner had more days with zero-weight parcels?",
    "Did any selected partner have parcels with weight = 0 but nonzero item count?",
    "Identify partners with major volume spikes last month.",
    "Which selected partner shows the most stable growth in the last 3 months?",
    "Show the standard deviation in daily volume per selected partner between 2019 and 2024."
]


MULTI_KPI_QUESTIONS = [
    "Compare total parcel volume this month across selected partners.",
    "Show the standard deviation in daily parcel volumes for each partner.",
    "Compare the max parcel weights for each partner over the last quarter. Can you generate the results in a Tabulated form",
    "Which partner has the lowest average daily volume this year?"
]

# ======================
# 📄 Chatbot Utilities
# ======================
def generate_metrics(df: pd.DataFrame, start_date: pd.Timestamp, end_date: pd.Timestamp) -> dict:
    period = df[(df['date'] >= start_date) & (df['date'] <= end_date)]
    daily = period.groupby('date').agg(total_items=('item', 'sum'), total_weight=('weight', 'sum'))
    volume_sum = int(period['item'].sum())
    volume_avg = round(daily['total_items'].mean(), 1)
    volume_max = int(daily['total_items'].max())
    volume_min = int(daily['total_items'].min())
    weight_sum = round(period['weight'].sum(), 2)
    weight_avg = round(weight_sum / volume_sum if volume_sum else 0, 2)
    weight_max = round(period['weight'].max(), 2)
    consistency_std = round(daily['total_items'].std(), 2)
    consistency_cv = round(consistency_std / volume_avg if volume_avg else 0, 2)
    activity_days = int(daily.shape[0])
    prev = df[(df['date'] >= start_date - pd.DateOffset(years=1)) & (df['date'] <= end_date - pd.DateOffset(years=1))]
    prev_sum = int(prev['item'].sum())
    growth = round((volume_sum - prev_sum) / prev_sum * 100, 2) if prev_sum else None
    busiest = daily['total_items'].idxmax().strftime('%Y-%m-%d')
    busiest_count = int(daily['total_items'].max())

    return {
        'Volume Sum': volume_sum,
        'Volume Avg/Day': volume_avg,
        'Volume Max': volume_max,
        'Volume Min': volume_min,
        'Weight Sum': weight_sum,
        'Weight Avg/Parcel': weight_avg,
        'Weight Max': weight_max,
        'Consistency StdDev': consistency_std,
        'Consistency CV': consistency_cv,
        'Active Days': activity_days,
        'YoY Growth (%)': growth,
        'Busiest Day': f"{busiest} ({busiest_count})"
    }

def generate_summary(metrics: dict) -> list:
    summary = []
    for partner, m in metrics.items():
        s = [
            f"**{partner}**",
            f"- **Volume:** Total={m['Volume Sum']}, Avg/Day={m['Volume Avg/Day']}, Max={m['Volume Max']}, Min={m['Volume Min']}",
            f"- **Weight:** Total={m['Weight Sum']} kg, Avg/Parcel={m['Weight Avg/Parcel']} kg, Max={m['Weight Max']} kg",
            f"- **Consistency:** StdDev={m['Consistency StdDev']}, CV={m['Consistency CV']}",
            f"- **Activity:** Active Days={m['Active Days']}"
        ]
        if m['YoY Growth (%)'] is not None:
            s.append(f"- **Growth:** YoY Change={m['YoY Growth (%)']}%")
        else:
            s.append("- **Growth:** No prior period data for YoY calculation")
        s.append(f"- **Busiest Day:** {m['Busiest Day']}")
        summary.extend(s)
        summary.append("")  # line break between partners
    return summary

def generate_yoy_growth(df: pd.DataFrame, start_date: str, end_date: str) -> str:
    """
    Calculate Year-over-Year (YoY) growth between the same periods in consecutive years.

    Parameters:
        df (DataFrame): DataFrame containing at least 'date' and 'item' columns
        start_date (str): Start date of current period (format: 'YYYY-MM-DD')
        end_date (str): End date of current period (format: 'YYYY-MM-DD')

    Returns:
        str: A human-readable YoY growth summary
    """
    df['date'] = pd.to_datetime(df['date'])
    
    start_2025 = pd.to_datetime(start_date)
    end_2025 = pd.to_datetime(end_date)
    start_2024 = start_2025.replace(year=2025 - 1)
    end_2024 = end_2025.replace(year=2025 - 1)

    current = df[(df['date'] >= start_2025) & (df['date'] <= end_2025)]
    last_year = df[(df['date'] >= start_2024) & (df['date'] <= end_2024)]

    total_2025 = current['item'].sum()
    total_2024 = last_year['item'].sum()

    if total_2024 == 0:
        return "⚠️ No data available for the same period in 2024."

    growth = ((total_2025 - total_2024) / total_2024) * 100
    return f"📈 YoY Growth ({start_2025.date()} to {end_2025.date()}): {growth:.2f}% ({total_2025:,} vs {total_2024:,})"
