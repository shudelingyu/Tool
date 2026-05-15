# data_formats.json 配置说明

## 概述

`data_formats.json` 定义了日志文件中各数据格式的解析规则。程序启动时读取此配置，动态生成列名和解析逻辑。当设备数据格式变化时（增删字段、调整顺序），只需修改此 JSON 文件，无需改动 Python 代码。

## 整体结构

```json
{
  "slave": { ... },   // 从手数据（逗号分隔）
  "boom":  { ... },   // 吊臂数据（逗号分隔）
  "master": { ... },  // 主手数据（空格分隔 key-value）
  "lout":  { ... }    // ADS 数据（正则检测，解析由代码处理）
}
```

## 格式检测机制

程序逐行读取日志，通过以下规则判断该行属于哪种格式：

| 格式 | 检测方式 | 说明 |
|------|---------|------|
| **slave** | `prefix: ","`, `counts: [142, 92]` | 逗号开头，切分后得到 142 或 92 列 |
| **boom** | `prefix: ","`, `counts: [36]` | 逗号开头，切分后得到 36 列 |
| **master** | `prefix: null` | 没有固定分隔符（空格切分），无逗号则尝试此格式 |
| **lout** | `detect_regex: "\\\\[ADS\\\\]"` | 行内容匹配 `[ADS]` 正则 |

> 检测顺序：slave → boom → master → lout。不匹配任何规则的行会被跳过。

---

## Slave（从手）格式详解

### 适用场景
从设备日志，逗号分隔的数值序列，有两种列数变体：**完整 142 列** 和 **简约 92 列**。

### 配置结构

```json
{
  "slave": {
    "detect": { "prefix": ",", "counts": [142, 92] },
    "array_vars": [ ... ],
    "flat_vars": [ ... ],
    "simple": { "array_start": 5, "array_end": 13 }
  }
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `detect.prefix` | string/null | 行的检测前缀/分隔符。`","` 表示行以逗号开头 |
| `detect.counts` | number[] | 该格式可能的列数列表，用于自动检测 |
| `array_vars` | object[] | **数组变量**：每个变量有多个索引（类似数组），按列主序交错排列 |
| `flat_vars` | object[] | **平坦变量**：排列在数组变量之前 |
| `simple.array_start` | number | 简约模式的起始索引（含） |
| `simple.array_end` | number | 简约模式的结束索引（**不含**，Python range 语义） |

### 列排列顺序

```
[flat_vars...] [array_vars[0]的第0索引] [array_vars[1]的第0索引] ... [array_vars[0]的第1索引] [array_vars[1]的第1索引] ...
```

即**列主序**（column-major）：先排列所有变量的第 0 个元素，再排列所有变量的第 1 个元素，依此类推。

例如 3 个变量（A:4, B:4, C:4），排列结果为：
`A[0] B[0] C[0] A[1] B[1] C[1] A[2] B[2] C[2] A[3] B[3] C[3]`

### array_vars 配置项

```json
[
  {"name": "tar_pos",    "count": 13},
  {"name": "cur_pos",    "count": 13},
  {"name": "tar_toq",    "count": 13},
  {"name": "cur_toq",    "count": 13},
  {"name": "status_word","count": 13},
  {"name": "control_word","count": 13},
  {"name": "error_code", "count": 13},
  {"name": "encoder1",   "count": 13},
  {"name": "encoder2",   "count": 13},
  {"name": "mode",       "count": 13}
]
```

- `name`: 变量名
- `count`: 该变量的元素个数（索引 0 ~ count-1）
- 列名生成规则：`变量名[索引]`，例如 `tar_pos[0]`、`tar_pos[1]` ...
- 10 个变量 × 13 个索引 = 130 列
- 在列主序排列中：第 0 列 = `tar_pos[0]`，第 1 列 = `cur_pos[0]`，...，第 10 列 = `tar_pos[1]`（因为 flat_vars 占用前 12 列）

### flat_vars 配置项

```json
[
  {"name": "pa",         "count": 6},
  {"name": "ff_PDO",     "count": 5},
  {"name": "motion_cmd", "count": 1}
]
```

- `name`: 变量名
- `count`: 该变量的元素个数
- 列名生成规则：
  - `count > 1`：`变量名[索引]`，例如 `pa[0]`、`pa[1]` ...
  - `count == 1`：直接使用变量名，例如 `motion_cmd`
- flat_vars 排在 array_vars **前面**（flat_vars 总列数 = 6 + 5 + 1 = 12）

### 简约模式（simple）

完整模式所有变量有 13 个索引（0-12），简约模式只取其中一段连续索引。

当前配置：
- `array_start = 5`：从索引 5 开始取
- `array_end = 13`：取到索引 12 结束（**13 不包含**）
- 实际取索引：`5, 6, 7, 8, 9, 10, 11, 12`，共 8 个索引

简约模式总列数验算：
- flat_vars：6 + 5 + 1 = **12 列**
- array_vars：10 变量 × 8 索引 = **80 列**
- 总计：12 + 80 = **92 列** ✓

### 完整列数验算

- flat_vars：6 + 5 + 1 = **12 列**
- array_vars：10 变量 × 13 索引 = **130 列**
- 总计：12 + 130 = **142 列** ✓

### 简约→完整映射

简约模式加载后如需转为完整模式，数组变量的处理方式：
- 简约只包含了索引 5-12 的数据
- 展开为完整 13 索引时，索引 0-4 用 0/NaN 填充
- flat_vars 部分直接对应，不需要调整

---

## Boom（吊臂）格式详解

### 适用场景
吊臂设备日志，逗号分隔的数值序列，固定 **36 列**。

### 配置结构

```json
{
  "boom": {
    "detect": { "prefix": ",", "counts": [36] },
    "array_vars": [
      {"name": "tar_pos",    "count": 4},
      {"name": "cur_pos",    "count": 4},
      {"name": "tar_toq",    "count": 4},
      {"name": "cur_toq",    "count": 4},
      {"name": "status_word","count": 4},
      {"name": "control_word","count": 4},
      {"name": "error_code", "count": 4},
      {"name": "encoder1",   "count": 4},
      {"name": "encoder2",   "count": 4}
    ]
  }
}
```

### 说明

- 没有 flat_vars，只有 array_vars
- 同样按列主序排列（同 slave）
- 9 变量 × 4 索引 = **36 列** ✓
- 没有简约模式（不需要 `simple` 字段）
- 列名示例：`tar_pos[0]`、`cur_pos[0]`、...、`tar_pos[1]`、`cur_pos[1]` ...

---

## Master（主手）格式详解

### 适用场景
主手设备日志，空格分隔的 key-value 对，每对包含标签前缀和数据值。

### 配置结构

```json
{
  "master": {
    "detect": { "prefix": null },
    "fields": [
      {"name": "cur_q",     "count": 8, "has_label": true},
      {"name": "cur_qabs",  "count": 8, "has_label": true},
      ...
    ]
  }
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `detect.prefix` | null | prefix 为 null，表示通过排除法识别（非逗号开头、非 ADS） |
| `fields` | object[] | 字段定义列表，按**出现顺序**排列 |

### fields 配置项

```json
{"name": "cur_q", "count": 8, "has_label": true}
```

- `name`: 字段名
- `count`: 该字段的数据点个数
- `has_label`: `true` 表示原始日志中该字段带有标签前缀（如 `cur_q1: 0.123`），解析时需跳过标签

### 列名生成规则

- `count > 1`：`字段名_索引`，例如 `cur_q_1`、`cur_q_2` ...
- `count == 1`：直接使用字段名，例如 `clipratio`

> 注意：master 使用下划线格式（`cur_q_1`），与 slave/boom 的中括号格式（`tar_pos[1]`）不同。这是为了保持与旧版本兼容。

### has_label 解析规则

当 `has_label = true` 时，原始日志行中每个值前有文本标签，例如：

```
cur_q1: 0.123 cur_q2: 0.456 cur_q3: 0.789
```

解析时，程序会：
1. 按空格切分为 token 序列
2. 每遇到一个以当前字段名开头的 token，判定为标签，**跳过**，取下一个 token 作为数值
3. 对每个字段重复 count 次，然后进入下一个字段

当 `has_label = false` 时：
1. 直接按顺序读取 count 个数值（没有标签可跳过）

### 列数验算

当前配置 19 个字段，总计 **119 列**：

| 字段名 | count | has_label | 列数 | 列名示例 |
|--------|-------|-----------|------|---------|
| cur_q | 8 | true | 8 | cur_q_1 ~ cur_q_8 |
| cur_qabs | 8 | true | 8 | cur_qabs_1 ~ cur_qabs_8 |
| tar_q | 8 | true | 8 | tar_q_1 ~ tar_q_8 |
| pdo6064 | 8 | true | 8 | pdo6064_1 ~ pdo6064_8 |
| pdo20a0 | 8 | true | 8 | pdo20a0_1 ~ pdo20a0_8 |
| cur_toq | 8 | true | 8 | cur_toq_1 ~ cur_toq_8 |
| tar_toq | 8 | true | 8 | tar_toq_1 ~ tar_toq_8 |
| gravityTau | 7 | true | 7 | gravityTau_1 ~ gravityTau_7 |
| feedbackTau | 7 | true | 7 | feedbackTau_1 ~ feedbackTau_7 |
| cur_endpos | 12 | true | 12 | cur_endpos_1 ~ cur_endpos_12 |
| clipratio | 1 | true | 1 | clipratio |
| hall | 1 | true | 1 | hall |
| io_finger_clutch | 1 | true | 1 | io_finger_clutch |
| control_word | 8 | true | 8 | control_word_1 ~ control_word_8 |
| status_word | 8 | true | 8 | status_word_1 ~ status_word_8 |
| error_code | 8 | true | 8 | error_code_1 ~ error_code_8 |
| mode_of_operation | 8 | true | 8 | mode_of_operation_1 ~ mode_of_operation_8 |
| motion_cmd | 1 | true | 1 | motion_cmd |
| view_angle | 1 | true | 1 | view_angle |
| **合计** | | | **119** | |

---

## LOUT/ADS 格式

```json
{
  "lout": {
    "detect_regex": "\\\\[ADS\\\\]"
  }
}
```

ADS 格式没有静态列定义。每行的列名和数量由实际日志内容动态决定，解析逻辑直接在 Python 代码中处理。配置中只需正确设置检测正则。

> JSON 字符串中 `\\\\` 表示一个字面反斜杠 `\`，因此 `"\\\\[ADS\\\\]"` 实际匹配文本中的 `[ADS]`。

---

## 修改示例

### 示例 1：给 slave 增加一个 array_var

假设新增变量 `target_vel`，每个从手轴一个值（13 个索引）：

```json
{"name": "target_vel", "count": 13}
```

插入 `array_vars` 数组 → 完整列数变为 142 + 13 = **155 列**
→ **必须同步更新** `detect.counts` 为 `[155, 92]`

### 示例 2：从 slave 删除一个 array_var

删除 `mode` 变量 → 完整列数变为 142 - 13 = **129 列**
→ **必须同步更新** `detect.counts` 为 `[129, 92]`

### 示例 3：给 master 增加字段

```json
{"name": "battery_level", "count": 1, "has_label": true}
```

插入 `fields` 数组 → 总列数变为 119 + 1 = **120 列**

### 示例 4：修改简约模式的范围

若改为从索引 4 取到索引 10（即 `4,5,6,7,8,9`，共 6 个索引）：

```json
"simple": { "array_start": 4, "array_end": 10 }
```

简约列数变为：flat_vars(12) + 10×6(60) = **72 列**
→ **必须同步更新** `detect.counts` 为 `[142, 72]`

---

## 修改后检查清单

1. **检测配置是否正确**
   - slave/boom：`counts` 数组中的数字必须与修改后的实际列数完全匹配
   - lout：正则表达式是否正确转义
   - 确保不同格式之间没有检测冲突（例如 slave 和 boom 不应有重叠的列数）

2. **列数验算**
   - slave 完整列数 = `sum(flat_vars[].count)` + `sum(array_vars[].count)`
   - slave 简约列数 = `sum(flat_vars[].count)` + `sum(array_vars[].count)` × `(simple.array_end - simple.array_start)`
   - boom 列数 = `sum(array_vars[].count)`
   - master 列数 = `sum(fields[].count)`

3. **列名是否唯一且有意义**
   - 检查不同变量之间是否会生成相同的列名
   - 避免使用特殊字符（列名会显示在 GUI 的树形控件中）

4. **与旧缓存文件的兼容性**
   - 修改配置后，旧的 parquet 缓存文件的列定义不匹配，**需要删除缓存**，让程序重新解析
   - 缓存文件位置：日志文件同目录下的 `*_combined_cache.parquet`
   - 或者直接在 GUI 中取消勾选"使用缓存"，强制重新解析

5. **重启程序验证**
   - 修改 JSON 后只需重启程序即可生效，**无需重新打包 EXE**
   - 如果程序启动报错，JSON 格式可能有误（如缺少逗号、多余逗号），可用 JSON 验证工具检查
