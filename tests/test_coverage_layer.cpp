// CPU-only fault injection; no Vulkan driver or GPU is initialized.
#include "../coverage/coverage_layer.cpp"
#include <cassert>
static bool failShader=false, failPipeline=false;
static int calls=0, destroyed=0, shaderDestroyed=0;
static VkShaderModule original=(VkShaderModule)100, repaired=(VkShaderModule)101;
static VkResult VKAPI_CALL shader(VkDevice,const VkShaderModuleCreateInfo*,const VkAllocationCallbacks*,VkShaderModule* out){
 if(failShader)return VK_ERROR_OUT_OF_HOST_MEMORY;
 *out=repaired;return VK_SUCCESS;
}
static void VKAPI_CALL destroyShader(VkDevice,VkShaderModule,const VkAllocationCallbacks*){++shaderDestroyed;}
static void VKAPI_CALL destroyPipeline(VkDevice,VkPipeline,const VkAllocationCallbacks*){++destroyed;}
static VkResult VKAPI_CALL pipelines(VkDevice,VkPipelineCache,uint32_t n,const VkGraphicsPipelineCreateInfo* in,const VkAllocationCallbacks*,VkPipeline* out){
 ++calls;
 const bool fallback=failShader||(failPipeline&&calls==2);
 assert(n==2);
 assert(in[0].pDepthStencilState->depthWriteEnable==!fallback);
 assert(in[0].pStages[0].module==(fallback?original:repaired));
 assert(in[1].pDepthStencilState->depthWriteEnable);
 assert(in[1].pStages[0].module==original); // colour pipeline untouched
 out[0]=(VkPipeline)200;out[1]=VK_NULL_HANDLE;
 if(failPipeline&&calls==1)return VK_ERROR_OUT_OF_HOST_MEMORY;
 out[1]=(VkPipeline)201;return VK_SUCCESS;
}
static PFN_vkVoidFunction VKAPI_CALL get(VkDevice,const char* name){
 if(!strcmp(name,"vkCreateShaderModule"))return (PFN_vkVoidFunction)shader;
 if(!strcmp(name,"vkDestroyShaderModule"))return (PFN_vkVoidFunction)destroyShader;
 if(!strcmp(name,"vkCreateGraphicsPipelines"))return (PFN_vkVoidFunction)pipelines;
 if(!strcmp(name,"vkDestroyPipeline"))return (PFN_vkVoidFunction)destroyPipeline;
 assert(false);return nullptr;
}
int main(){
 void* dispatch=(void*)42;auto h=(VkDevice)&dispatch;
 devices[key(h)]={get,true,{original}};
 VkPipelineShaderStageCreateInfo stage{VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO};
 stage.stage=VK_SHADER_STAGE_FRAGMENT_BIT;stage.module=original;stage.pName="main";
 VkPipelineMultisampleStateCreateInfo ms{VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO};ms.rasterizationSamples=VK_SAMPLE_COUNT_4_BIT;
 VkPipelineDepthStencilStateCreateInfo ds{VK_STRUCTURE_TYPE_PIPELINE_DEPTH_STENCIL_STATE_CREATE_INFO};ds.depthTestEnable=ds.depthWriteEnable=VK_TRUE;
 VkPipelineColorBlendStateCreateInfo cb{VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO}, colour=cb;colour.attachmentCount=1;
 VkPipelineRasterizationStateCreateInfo rs{VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO};
 VkGraphicsPipelineCreateInfo info{VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO};
 info.stageCount=1;info.pStages=&stage;info.pMultisampleState=&ms;info.pDepthStencilState=&ds;info.pColorBlendState=&cb;info.pRasterizationState=&rs;
 assert(eligible(info));ms.rasterizationSamples=VK_SAMPLE_COUNT_1_BIT;assert(!eligible(info));ms.rasterizationSamples=VK_SAMPLE_COUNT_4_BIT;
 ds.stencilTestEnable=VK_TRUE;assert(!eligible(info));ds.stencilTestEnable=VK_FALSE;
 VkGraphicsPipelineCreateInfo batch[2]={info,info};batch[1].pColorBlendState=&colour;
 for(int scenario=0;scenario<3;++scenario){
  failShader=scenario==1;failPipeline=scenario==2;calls=destroyed=shaderDestroyed=0;
  VkPipeline output[2]={};
  assert(p2CreateGraphicsPipelines(h,VK_NULL_HANDLE,2,batch,nullptr,output)==VK_SUCCESS);
  assert(calls==(failPipeline?2:1));assert(destroyed==(failPipeline?1:0));assert(shaderDestroyed==!failShader);
  assert(ds.depthWriteEnable&&stage.module==original); // caller's data unchanged
 }
 puts("Coverage layer: correction, mixed batches, shader failure and partial pipeline failure passed.");
}
