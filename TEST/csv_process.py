import argparse
import csv
from tabulate import tabulate
import sys

OPERATORS = {
    '>': lambda a, b: a > b,
    '<': lambda a, b: a < b,
    '=': lambda a, b: a == b
}

def average(nums):
    return sum(nums) / len(nums) if nums else None

AGGREGATES = {
    'avg': average,
    'min': min,
    'max': max
}

def get_args():
    parser = argparse.ArgumentParser(description="Простой CSV обработчик")
    parser.add_argument("--file", required=True, help="Путь к CSV файлу")
    parser.add_argument("--where", help="Условие фильтрации (например price>500)")
    parser.add_argument("--aggregate", help="Агрегация (например price=avg)")
    return parser.parse_args()

def parse_where(condition):
    # Найдем оператор в строке и разбьем на колонку и значение
    for op in OPERATORS:
        if op in condition:
            parts = condition.split(op)
            column = parts[0].strip()
            value = parts[1].strip()
            return column, op, value
    raise ValueError("Неправильное условие фильтрации")

def parse_aggregate(condition):
    if '=' not in condition:
        raise ValueError("Неправильный формат агрегации")
    column, agg_func = condition.split('=')
    return column.strip(), agg_func.strip()

def read_csv_file(path):
    with open(path, newline='') as f:
        reader = csv.DictReader(f)
        return list(reader)

def filter_data(data, column, op, value):
    op_func = OPERATORS[op]
    try:
        value = float(value)
        return [row for row in data if op_func(float(row[column]), value)]
    except ValueError:
        # Если не число, сравниваем как строки
        return [row for row in data if op_func(row[column], value)]

def aggregate_data(data, column, agg_name):
    numbers = [float(row[column]) for row in data]
    func = AGGREGATES.get(agg_name)
    if not func:
        raise ValueError("Неизвестная функция агрегации")
    return func(numbers)

def main():
    args = get_args()
    try:
        data = read_csv_file(args.file)

        if args.where:
            col, op, val = parse_where(args.where)
            data = filter_data(data, col, op, val)

        if args.aggregate:
            col, agg = parse_aggregate(args.aggregate)
            result = aggregate_data(data, col, agg)
            print(f"{agg.upper()} для колонки '{col}': {result}")
        else:
            print(tabulate(data, headers="keys", tablefmt="grid"))

    except Exception as e:
        print("Ошибка:", e)
        sys.exit(1)

if __name__ == "__main__":
    main()

