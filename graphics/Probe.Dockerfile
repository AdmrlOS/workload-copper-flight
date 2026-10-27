# Local verification artifact only. NVIDIA payload integration is separate.
# Export a release binary as the named probe-binary build context first.
ARG VERIFY_RUNTIME=workload-copper-flight:runtime-base
FROM ${VERIFY_RUNTIME}
COPY --from=probe-binary /copper-vulkan-depth-probe /usr/local/bin/copper-vulkan-depth-probe
ENV VK_DRIVER_FILES=/etc/vulkan/icd.d/nvidia_icd.json \
    VK_ICD_FILENAMES=/etc/vulkan/icd.d/nvidia_icd.json
ENTRYPOINT ["/usr/local/bin/copper-vulkan-depth-probe"]
CMD []
