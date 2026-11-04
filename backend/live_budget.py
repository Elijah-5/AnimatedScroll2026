"""Conservative per-request reservations, shared by every live-acceptance call."""
import json
import os

# USD / million tokens. Deliberately above the verified public rates, including
# peak/high-context tiers. Cache discounts are not assumed. Unknown models stop.
RATES={'deepseek-v4.1-flash-1017':(.5,2),'qwen3.7-plus':(1.1,4.4),'gpt-4o':(10,40)}

def reservation(body):
    model=body.get('model');rates=RATES.get(model)
    if not rates:raise ValueError('验收预算未登记此模型价格，未发送请求')
    if body.get('tools') or any(body.get(k) for k in ('web_search','enable_search','background')):raise ValueError('本轮验收禁止额外收费工具')
    # UTF-8 bytes plus template overhead is an upper bound for normal text
    # tokenization; images reserve 16K tokens each, not their base64 byte count.
    def size(value):
        if isinstance(value,dict) and value.get('type')=='image_url':return 16384
        if isinstance(value,dict):return sum(size(k)+size(v) for k,v in value.items())
        if isinstance(value,list):return sum(size(v) for v in value)
        return len(str(value).encode('utf-8'))+8
    inputs=size(body.get('messages',[]))+2048
    outputs=body.get('max_completion_tokens',body.get('max_tokens'))
    if not isinstance(outputs,int) or outputs<1:raise ValueError('验收请求必须明确输出上限')
    return dict(inputBound=inputs,outputBound=outputs,reservedUsd=(inputs*rates[0]+outputs*rates[1])/1000000,rates=rates)

def reserve(ledger,body):
    value=reservation(body)
    # 10 CNY/USD is a conservative *budget conversion*, not an exchange quote.
    # No top-up/payment is performed. $1 is the strict acceptance ceiling.
    cap=min(float(os.getenv('CREATION_LIVE_BUDGET_USD','1')),1)
    used=sum(r.get('accountedUsd',r.get('reservedUsd',0)) for r in ledger['requests'])
    if used+value['reservedUsd']>cap:raise ValueError('本轮真实验收费用预算不足，已保留进度，未发送请求')
    ledger.update(budgetUsd=cap,budgetCny=10,budgetConversionCnyPerUsd=10)
    return value

def account(row,usage):
    if not usage or not isinstance(usage.get('prompt_tokens'),int) or not isinstance(usage.get('completion_tokens'),int):return
    estimate=(usage['prompt_tokens']*row['rates'][0]+usage['completion_tokens']*row['rates'][1])/1000000
    row['accountedUsd']=estimate
    row['reservationExceeded']=estimate>row['reservedUsd']
