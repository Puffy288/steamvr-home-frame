// Correct alpha coverage only in fingerprint-matched four-sample depth pipelines.
// No command interception, resubmission, or render-target changes.
#include <vulkan/vulkan.h>
#include <vulkan/vk_layer.h>
#include <openssl/sha.h>
#include <array>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <mutex>
#include <unordered_map>
#include <unordered_set>
#include "coverage_spv.h"
#include <vector>
#include "expected.h"
struct Instance { VkInstance handle; PFN_vkGetInstanceProcAddr get; bool source2; };
struct Device { PFN_vkGetDeviceProcAddr get; bool source2; std::unordered_set<VkShaderModule> targets; };
static std::mutex guard;
static std::unordered_map<void*,Instance> instances;
static std::unordered_map<void*,Device> devices;
static void* key(void* h) { return h?*reinterpret_cast<void**>(h):nullptr; }
static Device device(VkDevice h) { std::lock_guard lock(guard); return devices.at(key(h)); }
extern "C" {
VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL p2GIPA(VkInstance,const char*);
VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL p2GDPA(VkDevice,const char*);
VKAPI_ATTR VkResult VKAPI_CALL p2CreateInstance(const VkInstanceCreateInfo* i,const VkAllocationCallbacks* a,VkInstance* out) {
 auto p=(VkLayerInstanceCreateInfo*)i->pNext;
 while(p&&(p->sType!=VK_STRUCTURE_TYPE_LOADER_INSTANCE_CREATE_INFO||p->function!=VK_LAYER_LINK_INFO))p=(VkLayerInstanceCreateInfo*)p->pNext;
 if(!p)return VK_ERROR_INITIALIZATION_FAILED;
 auto get=p->u.pLayerInfo->pfnNextGetInstanceProcAddr;p->u.pLayerInfo=p->u.pLayerInfo->pNext;
 auto r=((PFN_vkCreateInstance)get(nullptr,"vkCreateInstance"))(i,a,out);
 if(r==VK_SUCCESS){std::lock_guard lock(guard);instances[key(*out)]={*out,get,i->pApplicationInfo&&i->pApplicationInfo->pEngineName&&!strcmp(i->pApplicationInfo->pEngineName,"Source2")};}
 return r;
}
VKAPI_ATTR void VKAPI_CALL p2DestroyInstance(VkInstance h,const VkAllocationCallbacks* a) {
 Instance s;{std::lock_guard lock(guard);s=instances.at(key(h));instances.erase(key(h));}
 ((PFN_vkDestroyInstance)s.get(h,"vkDestroyInstance"))(h,a);
}
VKAPI_ATTR VkResult VKAPI_CALL p2CreateDevice(VkPhysicalDevice h,const VkDeviceCreateInfo* i,const VkAllocationCallbacks* a,VkDevice* out) {
 auto p=(VkLayerDeviceCreateInfo*)i->pNext;
 while(p&&(p->sType!=VK_STRUCTURE_TYPE_LOADER_DEVICE_CREATE_INFO||p->function!=VK_LAYER_LINK_INFO))p=(VkLayerDeviceCreateInfo*)p->pNext;
 if(!p)return VK_ERROR_INITIALIZATION_FAILED;
 auto get=p->u.pLayerInfo->pfnNextGetInstanceProcAddr;auto dp=p->u.pLayerInfo->pfnNextGetDeviceProcAddr;p->u.pLayerInfo=p->u.pLayerInfo->pNext;
 Instance s;{std::lock_guard lock(guard);s=instances.at(key(h));}
 auto r=((PFN_vkCreateDevice)get(s.handle,"vkCreateDevice"))(h,i,a,out);
 if(r==VK_SUCCESS){std::lock_guard lock(guard);devices[key(*out)]={dp,s.source2};}
 return r;
}
VKAPI_ATTR void VKAPI_CALL p2DestroyDevice(VkDevice h,const VkAllocationCallbacks* a) {
 auto d=device(h);{std::lock_guard lock(guard);devices.erase(key(h));}
 ((PFN_vkDestroyDevice)d.get(h,"vkDestroyDevice"))(h,a);
}
VKAPI_ATTR VkResult VKAPI_CALL p2CreateShaderModule(VkDevice h,const VkShaderModuleCreateInfo* i,const VkAllocationCallbacks* a,VkShaderModule* out) {
 auto d=device(h);auto next=(PFN_vkCreateShaderModule)d.get(h,"vkCreateShaderModule");
 auto result=next(h,i,a,out);
 if(result==VK_SUCCESS&&d.source2&&i->codeSize==expected_size&&!i->pNext){
  unsigned char digest[SHA256_DIGEST_LENGTH];SHA256((const unsigned char*)i->pCode,i->codeSize,digest);
  if(!memcmp(digest,expected_digest,sizeof(digest))){std::lock_guard lock(guard);devices.at(key(h)).targets.insert(*out);}
 }
 return result;
}
VKAPI_ATTR void VKAPI_CALL p2DestroyShaderModule(VkDevice h,VkShaderModule module,const VkAllocationCallbacks* a) {
 auto d=device(h);{std::lock_guard lock(guard);devices.at(key(h)).targets.erase(module);}
 ((PFN_vkDestroyShaderModule)d.get(h,"vkDestroyShaderModule"))(h,module,a);
}
static bool eligible(const VkGraphicsPipelineCreateInfo& i) {
 return !i.pNext&&i.pMultisampleState&&!i.pMultisampleState->pNext&&
  i.pMultisampleState->rasterizationSamples==VK_SAMPLE_COUNT_4_BIT&&
  !i.pMultisampleState->sampleShadingEnable&&i.pDepthStencilState&&
  !i.pDepthStencilState->pNext&&!i.pDepthStencilState->stencilTestEnable&&
  i.pDepthStencilState->depthTestEnable&&i.pDepthStencilState->depthWriteEnable&&
  i.pColorBlendState&&i.pColorBlendState->attachmentCount==0&&
  i.pRasterizationState&&!i.pRasterizationState->rasterizerDiscardEnable;
}
VKAPI_ATTR VkResult VKAPI_CALL p2CreateGraphicsPipelines(VkDevice h,VkPipelineCache cache,uint32_t count,const VkGraphicsPipelineCreateInfo* infos,const VkAllocationCallbacks* a,VkPipeline* pipelines) {
 auto d=device(h);auto next=(PFN_vkCreateGraphicsPipelines)d.get(h,"vkCreateGraphicsPipelines");
 if(!d.source2||d.targets.empty()||!count)return next(h,cache,count,infos,a,pipelines);
 std::vector<VkGraphicsPipelineCreateInfo> changed(infos,infos+count);
 std::vector<std::vector<VkPipelineShaderStageCreateInfo>> stages(count);
 unsigned matches=0;
 for(uint32_t i=0;i<count;++i){
  if(!eligible(infos[i]))continue;
  for(uint32_t j=0;j<infos[i].stageCount;++j){
   const auto& st=infos[i].pStages[j];
   if(st.stage==VK_SHADER_STAGE_FRAGMENT_BIT&&!st.pNext&&st.pName&&!strcmp(st.pName,"main")&&d.targets.count(st.module)){
    stages[i].assign(infos[i].pStages,infos[i].pStages+infos[i].stageCount);++matches;break;
   }
  }
 }
 if(!matches)return next(h,cache,count,infos,a,pipelines);
 // If shader/pipeline creation fails, omit only this optional depth write.
 // The original colour pass still tests and writes depth (verified in captures).
 // Never fall back to the original coverage defect. Colour and shadow pipelines
 // in the same batch retain their original state.
 auto safeFallback=[&]() {
  std::vector<VkGraphicsPipelineCreateInfo> safe(infos,infos+count);
  std::vector<VkPipelineDepthStencilStateCreateInfo> depth(count);
  for(uint32_t i=0;i<count;++i)if(!stages[i].empty()){
   depth[i]=*infos[i].pDepthStencilState;depth[i].depthWriteEnable=VK_FALSE;
   safe[i].pDepthStencilState=&depth[i];
  }
  fprintf(stderr,"PORT2 alpha coverage: correction unavailable; optional matched depth writes disabled.\n");
  return next(h,cache,count,safe.data(),a,pipelines);
 };
 VkShaderModuleCreateInfo sm{VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};sm.codeSize=sizeof(coverage_spv);sm.pCode=coverage_spv;
 VkShaderModule replacement=VK_NULL_HANDLE;
 auto create=(PFN_vkCreateShaderModule)d.get(h,"vkCreateShaderModule");
 auto destroy=(PFN_vkDestroyShaderModule)d.get(h,"vkDestroyShaderModule");
 if(create(h,&sm,a,&replacement)!=VK_SUCCESS)return safeFallback();
 for(uint32_t i=0;i<count;++i){
  if(stages[i].empty())continue;
  for(auto& st:stages[i])if(st.stage==VK_SHADER_STAGE_FRAGMENT_BIT&&d.targets.count(st.module))st.module=replacement;
  changed[i].pStages=stages[i].data();
 }
 auto result=next(h,cache,count,changed.data(),a,pipelines);destroy(h,replacement,a);
 fprintf(stderr,"PORT2 alpha coverage: corrected %u four-sample depth pipelines; result %d.\n",matches,result);
 if(result!=VK_SUCCESS){
  auto destroyPipeline=(PFN_vkDestroyPipeline)d.get(h,"vkDestroyPipeline");
  for(uint32_t i=0;i<count;++i){if(pipelines[i])destroyPipeline(h,pipelines[i],a);pipelines[i]=VK_NULL_HANDLE;}
  return safeFallback();
 }
 return result;
}
static PFN_vkVoidFunction intercept(const char* n) {
 if(!n)return nullptr;
#define MAP(x) if(!strcmp(n,"vk" #x))return (PFN_vkVoidFunction)p2##x
 MAP(CreateInstance);MAP(DestroyInstance);MAP(CreateDevice);MAP(DestroyDevice);MAP(CreateShaderModule);MAP(DestroyShaderModule);MAP(CreateGraphicsPipelines);
#undef MAP
 if(!strcmp(n,"vkGetInstanceProcAddr"))return (PFN_vkVoidFunction)p2GIPA;
 if(!strcmp(n,"vkGetDeviceProcAddr"))return (PFN_vkVoidFunction)p2GDPA;
 return nullptr;
}
VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL p2GIPA(VkInstance h,const char* n) {
 if(auto p=intercept(n))return p;
 if(!h)return nullptr;
 Instance s;{std::lock_guard lock(guard);s=instances.at(key(h));}return s.get(h,n);
}
VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL p2GDPA(VkDevice h,const char* n) {
 if(auto p=intercept(n))return p;
 auto d=device(h);return d.get(h,n);
}
__attribute__((visibility("default"))) VKAPI_ATTR VkResult VKAPI_CALL vkNegotiateLoaderLayerInterfaceVersion(VkNegotiateLayerInterface* i) {
 if(i->loaderLayerInterfaceVersion>2)i->loaderLayerInterfaceVersion=2;
 i->pfnGetInstanceProcAddr=p2GIPA;i->pfnGetDeviceProcAddr=p2GDPA;i->pfnGetPhysicalDeviceProcAddr=nullptr;return VK_SUCCESS;
}
}
