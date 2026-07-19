// Generated with hyprwayland-scanner 0.4.6. Made with vaxry's keyboard and ❤️.
// color_management_v1

/*
 This protocol's authors' copyright notice is:


    Copyright 2019 Sebastian Wick
    Copyright 2019 Erwin Burema
    Copyright 2020 AMD
    Copyright 2020-2024 Collabora, Ltd.
    Copyright 2024 Xaver Hugl
    Copyright 2022-2025 Red Hat, Inc.

    Permission is hereby granted, free of charge, to any person obtaining a
    copy of this software and associated documentation files (the "Software"),
    to deal in the Software without restriction, including without limitation
    the rights to use, copy, modify, merge, publish, distribute, sublicense,
    and/or sell copies of the Software, and to permit persons to whom the
    Software is furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice (including the next
    paragraph) shall be included in all copies or substantial portions of the
    Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL
    THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
    FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
    DEALINGS IN THE SOFTWARE.
  
*/

#pragma once

#include <functional>
#include <cstdint>
#include <string>
#include <wayland-server.h>

#define F std::function

struct wl_client;
struct wl_resource;

enum wpColorManagerV1Error : uint32_t {
    WP_COLOR_MANAGER_V1_ERROR_UNSUPPORTED_FEATURE = 0,
    WP_COLOR_MANAGER_V1_ERROR_SURFACE_EXISTS = 1,
};

enum wpColorManagerV1RenderIntent : uint32_t {
    WP_COLOR_MANAGER_V1_RENDER_INTENT_PERCEPTUAL = 0,
    WP_COLOR_MANAGER_V1_RENDER_INTENT_RELATIVE = 1,
    WP_COLOR_MANAGER_V1_RENDER_INTENT_SATURATION = 2,
    WP_COLOR_MANAGER_V1_RENDER_INTENT_ABSOLUTE = 3,
    WP_COLOR_MANAGER_V1_RENDER_INTENT_RELATIVE_BPC = 4,
    WP_COLOR_MANAGER_V1_RENDER_INTENT_ABSOLUTE_NO_ADAPTATION = 5,
};

enum wpColorManagerV1Feature : uint32_t {
    WP_COLOR_MANAGER_V1_FEATURE_ICC_V2_V4 = 0,
    WP_COLOR_MANAGER_V1_FEATURE_PARAMETRIC = 1,
    WP_COLOR_MANAGER_V1_FEATURE_SET_PRIMARIES = 2,
    WP_COLOR_MANAGER_V1_FEATURE_SET_TF_POWER = 3,
    WP_COLOR_MANAGER_V1_FEATURE_SET_LUMINANCES = 4,
    WP_COLOR_MANAGER_V1_FEATURE_SET_MASTERING_DISPLAY_PRIMARIES = 5,
    WP_COLOR_MANAGER_V1_FEATURE_EXTENDED_TARGET_VOLUME = 6,
    WP_COLOR_MANAGER_V1_FEATURE_WINDOWS_SCRGB = 7,
    WP_COLOR_MANAGER_V1_FEATURE_WINDOWS_BT2100 = 8,
};

enum wpColorManagerV1Primaries : uint32_t {
    WP_COLOR_MANAGER_V1_PRIMARIES_SRGB = 1,
    WP_COLOR_MANAGER_V1_PRIMARIES_PAL_M = 2,
    WP_COLOR_MANAGER_V1_PRIMARIES_PAL = 3,
    WP_COLOR_MANAGER_V1_PRIMARIES_NTSC = 4,
    WP_COLOR_MANAGER_V1_PRIMARIES_GENERIC_FILM = 5,
    WP_COLOR_MANAGER_V1_PRIMARIES_BT2020 = 6,
    WP_COLOR_MANAGER_V1_PRIMARIES_CIE1931_XYZ = 7,
    WP_COLOR_MANAGER_V1_PRIMARIES_DCI_P3 = 8,
    WP_COLOR_MANAGER_V1_PRIMARIES_DISPLAY_P3 = 9,
    WP_COLOR_MANAGER_V1_PRIMARIES_ADOBE_RGB = 10,
};

enum wpColorManagerV1TransferFunction : uint32_t {
    WP_COLOR_MANAGER_V1_TRANSFER_FUNCTION_BT1886 = 1,
    WP_COLOR_MANAGER_V1_TRANSFER_FUNCTION_GAMMA22 = 2,
    WP_COLOR_MANAGER_V1_TRANSFER_FUNCTION_GAMMA28 = 3,
    WP_COLOR_MANAGER_V1_TRANSFER_FUNCTION_ST240 = 4,
    WP_COLOR_MANAGER_V1_TRANSFER_FUNCTION_EXT_LINEAR = 5,
    WP_COLOR_MANAGER_V1_TRANSFER_FUNCTION_LOG_100 = 6,
    WP_COLOR_MANAGER_V1_TRANSFER_FUNCTION_LOG_316 = 7,
    WP_COLOR_MANAGER_V1_TRANSFER_FUNCTION_XVYCC = 8,
    WP_COLOR_MANAGER_V1_TRANSFER_FUNCTION_SRGB = 9,
    WP_COLOR_MANAGER_V1_TRANSFER_FUNCTION_EXT_SRGB = 10,
    WP_COLOR_MANAGER_V1_TRANSFER_FUNCTION_ST2084_PQ = 11,
    WP_COLOR_MANAGER_V1_TRANSFER_FUNCTION_ST428 = 12,
    WP_COLOR_MANAGER_V1_TRANSFER_FUNCTION_HLG = 13,
    WP_COLOR_MANAGER_V1_TRANSFER_FUNCTION_COMPOUND_POWER_2_4 = 14,
};

enum wpColorManagementSurfaceV1Error : uint32_t {
    WP_COLOR_MANAGEMENT_SURFACE_V1_ERROR_RENDER_INTENT = 0,
    WP_COLOR_MANAGEMENT_SURFACE_V1_ERROR_IMAGE_DESCRIPTION = 1,
    WP_COLOR_MANAGEMENT_SURFACE_V1_ERROR_INERT = 2,
};

enum wpColorManagementSurfaceFeedbackV1Error : uint32_t {
    WP_COLOR_MANAGEMENT_SURFACE_FEEDBACK_V1_ERROR_INERT = 0,
    WP_COLOR_MANAGEMENT_SURFACE_FEEDBACK_V1_ERROR_UNSUPPORTED_FEATURE = 1,
};

enum wpImageDescriptionCreatorIccV1Error : uint32_t {
    WP_IMAGE_DESCRIPTION_CREATOR_ICC_V1_ERROR_INCOMPLETE_SET = 0,
    WP_IMAGE_DESCRIPTION_CREATOR_ICC_V1_ERROR_ALREADY_SET = 1,
    WP_IMAGE_DESCRIPTION_CREATOR_ICC_V1_ERROR_BAD_FD = 2,
    WP_IMAGE_DESCRIPTION_CREATOR_ICC_V1_ERROR_BAD_SIZE = 3,
    WP_IMAGE_DESCRIPTION_CREATOR_ICC_V1_ERROR_OUT_OF_FILE = 4,
};

enum wpImageDescriptionCreatorParamsV1Error : uint32_t {
    WP_IMAGE_DESCRIPTION_CREATOR_PARAMS_V1_ERROR_INCOMPLETE_SET = 0,
    WP_IMAGE_DESCRIPTION_CREATOR_PARAMS_V1_ERROR_ALREADY_SET = 1,
    WP_IMAGE_DESCRIPTION_CREATOR_PARAMS_V1_ERROR_UNSUPPORTED_FEATURE = 2,
    WP_IMAGE_DESCRIPTION_CREATOR_PARAMS_V1_ERROR_INVALID_TF = 3,
    WP_IMAGE_DESCRIPTION_CREATOR_PARAMS_V1_ERROR_INVALID_PRIMARIES_NAMED = 4,
    WP_IMAGE_DESCRIPTION_CREATOR_PARAMS_V1_ERROR_INVALID_LUMINANCE = 5,
};

enum wpImageDescriptionV1Error : uint32_t {
    WP_IMAGE_DESCRIPTION_V1_ERROR_NOT_READY = 0,
    WP_IMAGE_DESCRIPTION_V1_ERROR_NO_INFORMATION = 1,
};

enum wpImageDescriptionV1Cause : uint32_t {
    WP_IMAGE_DESCRIPTION_V1_CAUSE_LOW_VERSION = 0,
    WP_IMAGE_DESCRIPTION_V1_CAUSE_UNSUPPORTED = 1,
    WP_IMAGE_DESCRIPTION_V1_CAUSE_OPERATING_SYSTEM = 2,
    WP_IMAGE_DESCRIPTION_V1_CAUSE_NO_OUTPUT = 3,
};


class CWpColorManagerV1;
class CWpColorManagementOutputV1;
class CWlOutput;
class CWpColorManagementSurfaceV1;
class CWlSurface;
class CWpColorManagementSurfaceFeedbackV1;
class CWlSurface;
class CWpImageDescriptionCreatorIccV1;
class CWpImageDescriptionCreatorParamsV1;
class CWpImageDescriptionV1;
class CWpImageDescriptionV1;
class CWpImageDescriptionReferenceV1;
class CWpImageDescriptionV1;
class CWpColorManagementOutputV1;
class CWpImageDescriptionV1;
class CWpColorManagementSurfaceV1;
class CWpImageDescriptionV1;
class CWpColorManagementSurfaceFeedbackV1;
class CWpImageDescriptionV1;
class CWpImageDescriptionV1;
class CWpImageDescriptionCreatorIccV1;
class CWpImageDescriptionV1;
class CWpImageDescriptionCreatorParamsV1;
class CWpImageDescriptionV1;
class CWpImageDescriptionV1;
class CWpImageDescriptionInfoV1;
class CWpImageDescriptionInfoV1;
class CWpImageDescriptionReferenceV1;

#ifndef HYPRWAYLAND_SCANNER_NO_INTERFACES
extern const wl_interface wp_color_manager_v1_interface;
extern const wl_interface wp_color_management_output_v1_interface;
extern const wl_interface wp_color_management_surface_v1_interface;
extern const wl_interface wp_color_management_surface_feedback_v1_interface;
extern const wl_interface wp_image_description_creator_icc_v1_interface;
extern const wl_interface wp_image_description_creator_params_v1_interface;
extern const wl_interface wp_image_description_v1_interface;
extern const wl_interface wp_image_description_info_v1_interface;
extern const wl_interface wp_image_description_reference_v1_interface;

#endif

struct CWpColorManagerV1DestroyWrapper {
    wl_listener listener;
    CWpColorManagerV1* parent = nullptr;
};
            

class CWpColorManagerV1 {
  public:
    CWpColorManagerV1(wl_client* client, uint32_t version, uint32_t id);
    ~CWpColorManagerV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CWpColorManagerV1*)> &&handler) {
        onDestroy = std::move(handler);
    }

    // set the data for this resource
    void setData(void* data) {
        pData = data;
    }

    // get the data for this resource
    void* data() {
        return pData;
    }

    // get the raw wl_resource ptr
    wl_resource* resource() {
        return pResource;
    }

    // get the client
    wl_client* client() {
        return wl_resource_get_client(pResource);
    }

    // send an error
    void error(uint32_t error, const std::string& message) {
        wl_resource_post_error(pResource, error, "%s", message.c_str());
    }

    // send out of memory
    void noMemory() {
        wl_resource_post_no_memory(pResource);
    }

    // get the resource version
    int version() {
        return wl_resource_get_version(pResource);
    }
            
    // --------------- Requests --------------- //

    void setDestroy(F<void(CWpColorManagerV1*)> &&handler);
    void setGetOutput(F<void(CWpColorManagerV1*, uint32_t, wl_resource*)> &&handler);
    void setGetSurface(F<void(CWpColorManagerV1*, uint32_t, wl_resource*)> &&handler);
    void setGetSurfaceFeedback(F<void(CWpColorManagerV1*, uint32_t, wl_resource*)> &&handler);
    void setCreateIccCreator(F<void(CWpColorManagerV1*, uint32_t)> &&handler);
    void setCreateParametricCreator(F<void(CWpColorManagerV1*, uint32_t)> &&handler);
    void setCreateWindowsScrgb(F<void(CWpColorManagerV1*, uint32_t)> &&handler);
    void setGetImageDescription(F<void(CWpColorManagerV1*, uint32_t, wl_resource*)> &&handler);
    void setCreateWindowsBt2100(F<void(CWpColorManagerV1*, uint32_t)> &&handler);

    // --------------- Events --------------- //

    void sendSupportedIntent(wpColorManagerV1RenderIntent);
    void sendSupportedFeature(wpColorManagerV1Feature);
    void sendSupportedTfNamed(wpColorManagerV1TransferFunction);
    void sendSupportedPrimariesNamed(wpColorManagerV1Primaries);
    void sendDone();
    void sendSupportedIntentRaw(wpColorManagerV1RenderIntent);
    void sendSupportedFeatureRaw(wpColorManagerV1Feature);
    void sendSupportedTfNamedRaw(wpColorManagerV1TransferFunction);
    void sendSupportedPrimariesNamedRaw(wpColorManagerV1Primaries);
    void sendDoneRaw();

  private:
    struct {
        F<void(CWpColorManagerV1*)> destroy;
        F<void(CWpColorManagerV1*, uint32_t, wl_resource*)> getOutput;
        F<void(CWpColorManagerV1*, uint32_t, wl_resource*)> getSurface;
        F<void(CWpColorManagerV1*, uint32_t, wl_resource*)> getSurfaceFeedback;
        F<void(CWpColorManagerV1*, uint32_t)> createIccCreator;
        F<void(CWpColorManagerV1*, uint32_t)> createParametricCreator;
        F<void(CWpColorManagerV1*, uint32_t)> createWindowsScrgb;
        F<void(CWpColorManagerV1*, uint32_t, wl_resource*)> getImageDescription;
        F<void(CWpColorManagerV1*, uint32_t)> createWindowsBt2100;
    } requests;

    void onDestroyCalled();

    F<void(CWpColorManagerV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CWpColorManagerV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};


struct CWpColorManagementOutputV1DestroyWrapper {
    wl_listener listener;
    CWpColorManagementOutputV1* parent = nullptr;
};
            

class CWpColorManagementOutputV1 {
  public:
    CWpColorManagementOutputV1(wl_client* client, uint32_t version, uint32_t id);
    ~CWpColorManagementOutputV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CWpColorManagementOutputV1*)> &&handler) {
        onDestroy = std::move(handler);
    }

    // set the data for this resource
    void setData(void* data) {
        pData = data;
    }

    // get the data for this resource
    void* data() {
        return pData;
    }

    // get the raw wl_resource ptr
    wl_resource* resource() {
        return pResource;
    }

    // get the client
    wl_client* client() {
        return wl_resource_get_client(pResource);
    }

    // send an error
    void error(uint32_t error, const std::string& message) {
        wl_resource_post_error(pResource, error, "%s", message.c_str());
    }

    // send out of memory
    void noMemory() {
        wl_resource_post_no_memory(pResource);
    }

    // get the resource version
    int version() {
        return wl_resource_get_version(pResource);
    }
            
    // --------------- Requests --------------- //

    void setDestroy(F<void(CWpColorManagementOutputV1*)> &&handler);
    void setGetImageDescription(F<void(CWpColorManagementOutputV1*, uint32_t)> &&handler);

    // --------------- Events --------------- //

    void sendImageDescriptionChanged();
    void sendImageDescriptionChangedRaw();

  private:
    struct {
        F<void(CWpColorManagementOutputV1*)> destroy;
        F<void(CWpColorManagementOutputV1*, uint32_t)> getImageDescription;
    } requests;

    void onDestroyCalled();

    F<void(CWpColorManagementOutputV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CWpColorManagementOutputV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};


struct CWpColorManagementSurfaceV1DestroyWrapper {
    wl_listener listener;
    CWpColorManagementSurfaceV1* parent = nullptr;
};
            

class CWpColorManagementSurfaceV1 {
  public:
    CWpColorManagementSurfaceV1(wl_client* client, uint32_t version, uint32_t id);
    ~CWpColorManagementSurfaceV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CWpColorManagementSurfaceV1*)> &&handler) {
        onDestroy = std::move(handler);
    }

    // set the data for this resource
    void setData(void* data) {
        pData = data;
    }

    // get the data for this resource
    void* data() {
        return pData;
    }

    // get the raw wl_resource ptr
    wl_resource* resource() {
        return pResource;
    }

    // get the client
    wl_client* client() {
        return wl_resource_get_client(pResource);
    }

    // send an error
    void error(uint32_t error, const std::string& message) {
        wl_resource_post_error(pResource, error, "%s", message.c_str());
    }

    // send out of memory
    void noMemory() {
        wl_resource_post_no_memory(pResource);
    }

    // get the resource version
    int version() {
        return wl_resource_get_version(pResource);
    }
            
    // --------------- Requests --------------- //

    void setDestroy(F<void(CWpColorManagementSurfaceV1*)> &&handler);
    void setSetImageDescription(F<void(CWpColorManagementSurfaceV1*, wl_resource*, uint32_t)> &&handler);
    void setUnsetImageDescription(F<void(CWpColorManagementSurfaceV1*)> &&handler);

    // --------------- Events --------------- //


  private:
    struct {
        F<void(CWpColorManagementSurfaceV1*)> destroy;
        F<void(CWpColorManagementSurfaceV1*, wl_resource*, uint32_t)> setImageDescription;
        F<void(CWpColorManagementSurfaceV1*)> unsetImageDescription;
    } requests;

    void onDestroyCalled();

    F<void(CWpColorManagementSurfaceV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CWpColorManagementSurfaceV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};


struct CWpColorManagementSurfaceFeedbackV1DestroyWrapper {
    wl_listener listener;
    CWpColorManagementSurfaceFeedbackV1* parent = nullptr;
};
            

class CWpColorManagementSurfaceFeedbackV1 {
  public:
    CWpColorManagementSurfaceFeedbackV1(wl_client* client, uint32_t version, uint32_t id);
    ~CWpColorManagementSurfaceFeedbackV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CWpColorManagementSurfaceFeedbackV1*)> &&handler) {
        onDestroy = std::move(handler);
    }

    // set the data for this resource
    void setData(void* data) {
        pData = data;
    }

    // get the data for this resource
    void* data() {
        return pData;
    }

    // get the raw wl_resource ptr
    wl_resource* resource() {
        return pResource;
    }

    // get the client
    wl_client* client() {
        return wl_resource_get_client(pResource);
    }

    // send an error
    void error(uint32_t error, const std::string& message) {
        wl_resource_post_error(pResource, error, "%s", message.c_str());
    }

    // send out of memory
    void noMemory() {
        wl_resource_post_no_memory(pResource);
    }

    // get the resource version
    int version() {
        return wl_resource_get_version(pResource);
    }
            
    // --------------- Requests --------------- //

    void setDestroy(F<void(CWpColorManagementSurfaceFeedbackV1*)> &&handler);
    void setGetPreferred(F<void(CWpColorManagementSurfaceFeedbackV1*, uint32_t)> &&handler);
    void setGetPreferredParametric(F<void(CWpColorManagementSurfaceFeedbackV1*, uint32_t)> &&handler);

    // --------------- Events --------------- //

    void sendPreferredChanged(uint32_t);
    void sendPreferredChanged2(uint32_t, uint32_t);
    void sendPreferredChangedRaw(uint32_t);
    void sendPreferredChanged2Raw(uint32_t, uint32_t);

  private:
    struct {
        F<void(CWpColorManagementSurfaceFeedbackV1*)> destroy;
        F<void(CWpColorManagementSurfaceFeedbackV1*, uint32_t)> getPreferred;
        F<void(CWpColorManagementSurfaceFeedbackV1*, uint32_t)> getPreferredParametric;
    } requests;

    void onDestroyCalled();

    F<void(CWpColorManagementSurfaceFeedbackV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CWpColorManagementSurfaceFeedbackV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};


struct CWpImageDescriptionCreatorIccV1DestroyWrapper {
    wl_listener listener;
    CWpImageDescriptionCreatorIccV1* parent = nullptr;
};
            

class CWpImageDescriptionCreatorIccV1 {
  public:
    CWpImageDescriptionCreatorIccV1(wl_client* client, uint32_t version, uint32_t id);
    ~CWpImageDescriptionCreatorIccV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CWpImageDescriptionCreatorIccV1*)> &&handler) {
        onDestroy = std::move(handler);
    }

    // set the data for this resource
    void setData(void* data) {
        pData = data;
    }

    // get the data for this resource
    void* data() {
        return pData;
    }

    // get the raw wl_resource ptr
    wl_resource* resource() {
        return pResource;
    }

    // get the client
    wl_client* client() {
        return wl_resource_get_client(pResource);
    }

    // send an error
    void error(uint32_t error, const std::string& message) {
        wl_resource_post_error(pResource, error, "%s", message.c_str());
    }

    // send out of memory
    void noMemory() {
        wl_resource_post_no_memory(pResource);
    }

    // get the resource version
    int version() {
        return wl_resource_get_version(pResource);
    }
            
    // --------------- Requests --------------- //

    void setCreate(F<void(CWpImageDescriptionCreatorIccV1*, uint32_t)> &&handler);
    void setSetIccFile(F<void(CWpImageDescriptionCreatorIccV1*, int32_t, uint32_t, uint32_t)> &&handler);

    // --------------- Events --------------- //


  private:
    struct {
        F<void(CWpImageDescriptionCreatorIccV1*, uint32_t)> create;
        F<void(CWpImageDescriptionCreatorIccV1*, int32_t, uint32_t, uint32_t)> setIccFile;
    } requests;

    void onDestroyCalled();

    F<void(CWpImageDescriptionCreatorIccV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CWpImageDescriptionCreatorIccV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};


struct CWpImageDescriptionCreatorParamsV1DestroyWrapper {
    wl_listener listener;
    CWpImageDescriptionCreatorParamsV1* parent = nullptr;
};
            

class CWpImageDescriptionCreatorParamsV1 {
  public:
    CWpImageDescriptionCreatorParamsV1(wl_client* client, uint32_t version, uint32_t id);
    ~CWpImageDescriptionCreatorParamsV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CWpImageDescriptionCreatorParamsV1*)> &&handler) {
        onDestroy = std::move(handler);
    }

    // set the data for this resource
    void setData(void* data) {
        pData = data;
    }

    // get the data for this resource
    void* data() {
        return pData;
    }

    // get the raw wl_resource ptr
    wl_resource* resource() {
        return pResource;
    }

    // get the client
    wl_client* client() {
        return wl_resource_get_client(pResource);
    }

    // send an error
    void error(uint32_t error, const std::string& message) {
        wl_resource_post_error(pResource, error, "%s", message.c_str());
    }

    // send out of memory
    void noMemory() {
        wl_resource_post_no_memory(pResource);
    }

    // get the resource version
    int version() {
        return wl_resource_get_version(pResource);
    }
            
    // --------------- Requests --------------- //

    void setCreate(F<void(CWpImageDescriptionCreatorParamsV1*, uint32_t)> &&handler);
    void setSetTfNamed(F<void(CWpImageDescriptionCreatorParamsV1*, uint32_t)> &&handler);
    void setSetTfPower(F<void(CWpImageDescriptionCreatorParamsV1*, uint32_t)> &&handler);
    void setSetPrimariesNamed(F<void(CWpImageDescriptionCreatorParamsV1*, uint32_t)> &&handler);
    void setSetPrimaries(F<void(CWpImageDescriptionCreatorParamsV1*, int32_t, int32_t, int32_t, int32_t, int32_t, int32_t, int32_t, int32_t)> &&handler);
    void setSetLuminances(F<void(CWpImageDescriptionCreatorParamsV1*, uint32_t, uint32_t, uint32_t)> &&handler);
    void setSetMasteringDisplayPrimaries(F<void(CWpImageDescriptionCreatorParamsV1*, int32_t, int32_t, int32_t, int32_t, int32_t, int32_t, int32_t, int32_t)> &&handler);
    void setSetMasteringLuminance(F<void(CWpImageDescriptionCreatorParamsV1*, uint32_t, uint32_t)> &&handler);
    void setSetMaxCll(F<void(CWpImageDescriptionCreatorParamsV1*, uint32_t)> &&handler);
    void setSetMaxFall(F<void(CWpImageDescriptionCreatorParamsV1*, uint32_t)> &&handler);

    // --------------- Events --------------- //


  private:
    struct {
        F<void(CWpImageDescriptionCreatorParamsV1*, uint32_t)> create;
        F<void(CWpImageDescriptionCreatorParamsV1*, uint32_t)> setTfNamed;
        F<void(CWpImageDescriptionCreatorParamsV1*, uint32_t)> setTfPower;
        F<void(CWpImageDescriptionCreatorParamsV1*, uint32_t)> setPrimariesNamed;
        F<void(CWpImageDescriptionCreatorParamsV1*, int32_t, int32_t, int32_t, int32_t, int32_t, int32_t, int32_t, int32_t)> setPrimaries;
        F<void(CWpImageDescriptionCreatorParamsV1*, uint32_t, uint32_t, uint32_t)> setLuminances;
        F<void(CWpImageDescriptionCreatorParamsV1*, int32_t, int32_t, int32_t, int32_t, int32_t, int32_t, int32_t, int32_t)> setMasteringDisplayPrimaries;
        F<void(CWpImageDescriptionCreatorParamsV1*, uint32_t, uint32_t)> setMasteringLuminance;
        F<void(CWpImageDescriptionCreatorParamsV1*, uint32_t)> setMaxCll;
        F<void(CWpImageDescriptionCreatorParamsV1*, uint32_t)> setMaxFall;
    } requests;

    void onDestroyCalled();

    F<void(CWpImageDescriptionCreatorParamsV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CWpImageDescriptionCreatorParamsV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};


struct CWpImageDescriptionV1DestroyWrapper {
    wl_listener listener;
    CWpImageDescriptionV1* parent = nullptr;
};
            

class CWpImageDescriptionV1 {
  public:
    CWpImageDescriptionV1(wl_client* client, uint32_t version, uint32_t id);
    ~CWpImageDescriptionV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CWpImageDescriptionV1*)> &&handler) {
        onDestroy = std::move(handler);
    }

    // set the data for this resource
    void setData(void* data) {
        pData = data;
    }

    // get the data for this resource
    void* data() {
        return pData;
    }

    // get the raw wl_resource ptr
    wl_resource* resource() {
        return pResource;
    }

    // get the client
    wl_client* client() {
        return wl_resource_get_client(pResource);
    }

    // send an error
    void error(uint32_t error, const std::string& message) {
        wl_resource_post_error(pResource, error, "%s", message.c_str());
    }

    // send out of memory
    void noMemory() {
        wl_resource_post_no_memory(pResource);
    }

    // get the resource version
    int version() {
        return wl_resource_get_version(pResource);
    }
            
    // --------------- Requests --------------- //

    void setDestroy(F<void(CWpImageDescriptionV1*)> &&handler);
    void setGetInformation(F<void(CWpImageDescriptionV1*, uint32_t)> &&handler);

    // --------------- Events --------------- //

    void sendFailed(wpImageDescriptionV1Cause, const char*);
    void sendReady(uint32_t);
    void sendReady2(uint32_t, uint32_t);
    void sendFailedRaw(wpImageDescriptionV1Cause, const char*);
    void sendReadyRaw(uint32_t);
    void sendReady2Raw(uint32_t, uint32_t);

  private:
    struct {
        F<void(CWpImageDescriptionV1*)> destroy;
        F<void(CWpImageDescriptionV1*, uint32_t)> getInformation;
    } requests;

    void onDestroyCalled();

    F<void(CWpImageDescriptionV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CWpImageDescriptionV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};


struct CWpImageDescriptionInfoV1DestroyWrapper {
    wl_listener listener;
    CWpImageDescriptionInfoV1* parent = nullptr;
};
            

class CWpImageDescriptionInfoV1 {
  public:
    CWpImageDescriptionInfoV1(wl_client* client, uint32_t version, uint32_t id);
    ~CWpImageDescriptionInfoV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CWpImageDescriptionInfoV1*)> &&handler) {
        onDestroy = std::move(handler);
    }

    // set the data for this resource
    void setData(void* data) {
        pData = data;
    }

    // get the data for this resource
    void* data() {
        return pData;
    }

    // get the raw wl_resource ptr
    wl_resource* resource() {
        return pResource;
    }

    // get the client
    wl_client* client() {
        return wl_resource_get_client(pResource);
    }

    // send an error
    void error(uint32_t error, const std::string& message) {
        wl_resource_post_error(pResource, error, "%s", message.c_str());
    }

    // send out of memory
    void noMemory() {
        wl_resource_post_no_memory(pResource);
    }

    // get the resource version
    int version() {
        return wl_resource_get_version(pResource);
    }
            
    // --------------- Requests --------------- //


    // --------------- Events --------------- //

    void sendDone();
    void sendIccFile(int32_t, uint32_t);
    void sendPrimaries(int32_t, int32_t, int32_t, int32_t, int32_t, int32_t, int32_t, int32_t);
    void sendPrimariesNamed(uint32_t);
    void sendTfPower(uint32_t);
    void sendTfNamed(uint32_t);
    void sendLuminances(uint32_t, uint32_t, uint32_t);
    void sendTargetPrimaries(int32_t, int32_t, int32_t, int32_t, int32_t, int32_t, int32_t, int32_t);
    void sendTargetLuminance(uint32_t, uint32_t);
    void sendTargetMaxCll(uint32_t);
    void sendTargetMaxFall(uint32_t);
    void sendDoneRaw();
    void sendIccFileRaw(int32_t, uint32_t);
    void sendPrimariesRaw(int32_t, int32_t, int32_t, int32_t, int32_t, int32_t, int32_t, int32_t);
    void sendPrimariesNamedRaw(uint32_t);
    void sendTfPowerRaw(uint32_t);
    void sendTfNamedRaw(uint32_t);
    void sendLuminancesRaw(uint32_t, uint32_t, uint32_t);
    void sendTargetPrimariesRaw(int32_t, int32_t, int32_t, int32_t, int32_t, int32_t, int32_t, int32_t);
    void sendTargetLuminanceRaw(uint32_t, uint32_t);
    void sendTargetMaxCllRaw(uint32_t);
    void sendTargetMaxFallRaw(uint32_t);

  private:
    struct {
    } requests;

    void onDestroyCalled();

    F<void(CWpImageDescriptionInfoV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CWpImageDescriptionInfoV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};


struct CWpImageDescriptionReferenceV1DestroyWrapper {
    wl_listener listener;
    CWpImageDescriptionReferenceV1* parent = nullptr;
};
            

class CWpImageDescriptionReferenceV1 {
  public:
    CWpImageDescriptionReferenceV1(wl_client* client, uint32_t version, uint32_t id);
    ~CWpImageDescriptionReferenceV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CWpImageDescriptionReferenceV1*)> &&handler) {
        onDestroy = std::move(handler);
    }

    // set the data for this resource
    void setData(void* data) {
        pData = data;
    }

    // get the data for this resource
    void* data() {
        return pData;
    }

    // get the raw wl_resource ptr
    wl_resource* resource() {
        return pResource;
    }

    // get the client
    wl_client* client() {
        return wl_resource_get_client(pResource);
    }

    // send an error
    void error(uint32_t error, const std::string& message) {
        wl_resource_post_error(pResource, error, "%s", message.c_str());
    }

    // send out of memory
    void noMemory() {
        wl_resource_post_no_memory(pResource);
    }

    // get the resource version
    int version() {
        return wl_resource_get_version(pResource);
    }
            
    // --------------- Requests --------------- //

    void setDestroy(F<void(CWpImageDescriptionReferenceV1*)> &&handler);

    // --------------- Events --------------- //


  private:
    struct {
        F<void(CWpImageDescriptionReferenceV1*)> destroy;
    } requests;

    void onDestroyCalled();

    F<void(CWpImageDescriptionReferenceV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CWpImageDescriptionReferenceV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};



#undef F
