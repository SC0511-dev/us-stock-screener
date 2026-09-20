# K 线形态对照表

共 **61** 种形态，底层由 TA-Lib 识别，口径与主流看盘软件一致。

**信号取值**：正数看涨，负数看跌，0 表示未形成该形态；绝对值 200 表示强化确认型。

**可靠度**：标注「高」的是业界公认信号较强、实战中更常参考的形态。但即便如此，单一形态的胜率仍然有限，务必结合趋势位置与成交量判断。

| 中文名 | TA-Lib 函数 | 方向倾向 | 可靠度 | 条件 key |
| --- | --- | --- | --- | --- |
| 三只乌鸦 | `CDL3BLACKCROWS` | 偏空 | 高 | `pat_cdl3blackcrows` |
| 三星形态 | `CDLTRISTAR` | 双向 | 高 | `pat_cdltristar` |
| 三线打击 | `CDL3LINESTRIKE` | 双向 | 高 | `pat_cdl3linestrike` |
| 上升/下降三法 | `CDLRISEFALL3METHODS` | 双向 | 高 | `pat_cdlrisefall3methods` |
| 上吊线 | `CDLHANGINGMAN` | 偏空 | 高 | `pat_cdlhangingman` |
| 乌云压顶 | `CDLDARKCLOUDCOVER` | 偏空 | 高 | `pat_cdldarkcloudcover` |
| 刺透形态 | `CDLPIERCING` | 偏多 | 高 | `pat_cdlpiercing` |
| 十字晨星 | `CDLMORNINGDOJISTAR` | 偏多 | 高 | `pat_cdlmorningdojistar` |
| 十字暮星 | `CDLEVENINGDOJISTAR` | 偏空 | 高 | `pat_cdleveningdojistar` |
| 反冲形态 | `CDLKICKING` | 双向 | 高 | `pat_cdlkicking` |
| 吞没形态 | `CDLENGULFING` | 双向 | 高 | `pat_cdlengulfing` |
| 射击之星 | `CDLSHOOTINGSTAR` | 偏空 | 高 | `pat_cdlshootingstar` |
| 弃婴 | `CDLABANDONEDBABY` | 双向 | 高 | `pat_cdlabandonedbaby` |
| 晨星 | `CDLMORNINGSTAR` | 偏多 | 高 | `pat_cdlmorningstar` |
| 暮星 | `CDLEVENINGSTAR` | 偏空 | 高 | `pat_cdleveningstar` |
| 红三兵 | `CDL3WHITESOLDIERS` | 偏多 | 高 | `pat_cdl3whitesoldiers` |
| 锤头线 | `CDLHAMMER` | 偏多 | 高 | `pat_cdlhammer` |
| 三内部上涨/下跌 | `CDL3INSIDE` | 双向 | 一般 | `pat_cdl3inside` |
| 三外部上涨/下跌 | `CDL3OUTSIDE` | 双向 | 一般 | `pat_cdl3outside` |
| 三胞胎乌鸦 | `CDLIDENTICAL3CROWS` | 偏空 | 一般 | `pat_cdlidentical3crows` |
| 两只乌鸦 | `CDL2CROWS` | 偏空 | 一般 | `pat_cdl2crows` |
| 修正陷阱形态 | `CDLHIKKAKEMOD` | 双向 | 一般 | `pat_cdlhikkakemod` |
| 倒锤头 | `CDLINVERTEDHAMMER` | 偏多 | 一般 | `pat_cdlinvertedhammer` |
| 停顿形态 | `CDLSTALLEDPATTERN` | 偏空 | 一般 | `pat_cdlstalledpattern` |
| 光头光脚 | `CDLMARUBOZU` | 双向 | 一般 | `pat_cdlmarubozu` |
| 分离线 | `CDLSEPARATINGLINES` | 双向 | 一般 | `pat_cdlseparatinglines` |
| 十字孕线 | `CDLHARAMICROSS` | 双向 | 一般 | `pat_cdlharamicross` |
| 十字星 | `CDLDOJISTAR` | 双向 | 一般 | `pat_cdldojistar` |
| 十字线 | `CDLDOJI` | 双向 | 一般 | `pat_cdldoji` |
| 南方三星 | `CDL3STARSINSOUTH` | 偏多 | 一般 | `pat_cdl3starsinsouth` |
| 反击线 | `CDLCOUNTERATTACK` | 双向 | 一般 | `pat_cdlcounterattack` |
| 向上跳空两乌鸦 | `CDLUPSIDEGAP2CROWS` | 偏空 | 一般 | `pat_cdlupsidegap2crows` |
| 墓碑十字 | `CDLGRAVESTONEDOJI` | 偏空 | 一般 | `pat_cdlgravestonedoji` |
| 大敌当前 | `CDLADVANCEBLOCK` | 偏空 | 一般 | `pat_cdladvanceblock` |
| 奇特三河床 | `CDLUNIQUE3RIVER` | 偏多 | 一般 | `pat_cdlunique3river` |
| 孕线 | `CDLHARAMI` | 双向 | 一般 | `pat_cdlharami` |
| 家鸽 | `CDLHOMINGPIGEON` | 偏多 | 一般 | `pat_cdlhomingpigeon` |
| 捉腰带线 | `CDLBELTHOLD` | 双向 | 一般 | `pat_cdlbelthold` |
| 探水竿 | `CDLTAKURI` | 偏多 | 一般 | `pat_cdltakuri` |
| 插入线 | `CDLTHRUSTING` | 偏空 | 一般 | `pat_cdlthrusting` |
| 收盘光头光脚 | `CDLCLOSINGMARUBOZU` | 双向 | 一般 | `pat_cdlclosingmarubozu` |
| 条形三明治 | `CDLSTICKSANDWICH` | 偏多 | 一般 | `pat_cdlsticksandwich` |
| 梯底 | `CDLLADDERBOTTOM` | 偏多 | 一般 | `pat_cdlladderbottom` |
| 相同低价 | `CDLMATCHINGLOW` | 偏多 | 一般 | `pat_cdlmatchinglow` |
| 短实体蜡烛 | `CDLSHORTLINE` | 双向 | 一般 | `pat_cdlshortline` |
| 纺锤线 | `CDLSPINNINGTOP` | 双向 | 一般 | `pat_cdlspinningtop` |
| 脱离 | `CDLBREAKAWAY` | 双向 | 一般 | `pat_cdlbreakaway` |
| 藏婴吞没 | `CDLCONCEALBABYSWALL` | 偏多 | 一般 | `pat_cdlconcealbabyswall` |
| 蜻蜓十字 | `CDLDRAGONFLYDOJI` | 偏多 | 一般 | `pat_cdldragonflydoji` |
| 跳空三法 | `CDLXSIDEGAP3METHODS` | 双向 | 一般 | `pat_cdlxsidegap3methods` |
| 跳空并列阳线 | `CDLGAPSIDESIDEWHITE` | 双向 | 一般 | `pat_cdlgapsidesidewhite` |
| 跳空并列阴阳线 | `CDLTASUKIGAP` | 双向 | 一般 | `pat_cdltasukigap` |
| 铺垫形态 | `CDLMATHOLD` | 偏多 | 一般 | `pat_cdlmathold` |
| 长实体蜡烛 | `CDLLONGLINE` | 双向 | 一般 | `pat_cdllongline` |
| 长缺影反冲 | `CDLKICKINGBYLENGTH` | 双向 | 一般 | `pat_cdlkickingbylength` |
| 长腿十字 | `CDLLONGLEGGEDDOJI` | 双向 | 一般 | `pat_cdllongleggeddoji` |
| 陷阱形态 | `CDLHIKKAKE` | 双向 | 一般 | `pat_cdlhikkake` |
| 颈上线 | `CDLONNECK` | 偏空 | 一般 | `pat_cdlonneck` |
| 颈内线 | `CDLINNECK` | 偏空 | 一般 | `pat_cdlinneck` |
| 风高浪大线 | `CDLHIGHWAVE` | 双向 | 一般 | `pat_cdlhighwave` |
| 黄包车夫 | `CDLRICKSHAWMAN` | 双向 | 一般 | `pat_cdlrickshawman` |

## 组合条件

| 条件 key | 说明 |
| --- | --- |
| `pat_any_bull_hq` | 出现任一高可靠度看涨形态 |
| `pat_any_bear_hq` | 出现任一高可靠度看跌形态 |
