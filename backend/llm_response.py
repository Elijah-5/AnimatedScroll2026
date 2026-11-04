"""Safe structured-response handling. Never parse hidden reasoning as authoring output."""
import logging
import os

logger=logging.getLogger(__name__)

class ModelResponseError(ValueError):
    def __init__(self,code,message,diagnostics=None):
        super().__init__(message);self.code=code;self.diagnostics=diagnostics or {}

def options(model,budget=12000):
    result=dict(max_tokens=max(budget,int(os.getenv('AIHUBMIX_MAX_OUTPUT_TOKENS','12000'))))
    if 'deepseek' in model.lower():
        result['extra_body']={'thinking':{'type':os.getenv('AIHUBMIX_THINKING','disabled')}}
        result['response_format']={'type':'json_object'}
    return result

def json_text(response):
    choices=getattr(response,'choices',None)
    if not choices:raise ModelResponseError('empty_response','模型服务没有返回有效回复。资料已保留，请点击重试。')
    choice=choices[0];message=choice.message
    usage=getattr(response,'usage',None)
    details=getattr(usage,'completion_tokens_details',None)
    diagnostics=dict(model=getattr(response,'model',''),finishReason=getattr(choice,'finish_reason',None),completionTokens=getattr(usage,'completion_tokens',None),reasoningTokens=getattr(details,'reasoning_tokens',None),hasReasoning=bool(getattr(message,'reasoning_content',None)))
    raw=getattr(message,'content',None)
    if getattr(message,'refusal',None) or diagnostics['finishReason']=='content_filter':raise ModelResponseError('refused','模型服务未提供本次生成内容。资料已保留，请检查请求或切换模型后重试。',diagnostics)
    if diagnostics['finishReason']=='length':
        logger.warning('structured response truncated: %s',diagnostics)
        raise ModelResponseError('truncated_response','模型输出达到长度上限，未得到完整结果。资料已保留，请减少单次内容或提高输出预算后重试。',diagnostics)
    if not isinstance(raw,str) or not raw.strip():
        logger.warning('structured response empty: %s',diagnostics)
        raise ModelResponseError('empty_response','模型返回空内容，未获得可解析结果。资料已保留，请点击重试。',diagnostics)
    return raw.strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip()
