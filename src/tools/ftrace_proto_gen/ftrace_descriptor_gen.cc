/*
 * Copyright (C) 2018 The Android Open Source Project
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#include "src/tools/ftrace_proto_gen/ftrace_descriptor_gen.h"

#include <google/protobuf/descriptor.h>
#include <google/protobuf/descriptor.pb.h>

namespace perfetto {

void GenerateFtraceDescriptors(
    const google::protobuf::DescriptorPool& descriptor_pool,
    std::ostream* fout) {
  const google::protobuf::Descriptor* ftrace_event =
      descriptor_pool.FindMessageTypeByName("perfetto.protos.FtraceEvent");
  const google::protobuf::OneofDescriptor* one_of_event =
      ftrace_event->FindOneofByName("event");

  // Find max id for any ftrace event.
  int max_id = 0;
  for (int i = 0; i < one_of_event->field_count(); i++)
    max_id = std::max(max_id, one_of_event->field(i)->number());

  *fout << R"(/*
 * Copyright (C) 2017 The Android Open Source Project
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

)";
  *fout << "// Autogenerated by:\n";
  *fout << std::string("// ") + __FILE__ + "\n";
  *fout << "// Do not edit.\n";
  *fout << R"(
#include "src/trace_processor/importers/ftrace/ftrace_descriptors.h"

namespace perfetto {
namespace trace_processor {
namespace {

std::array<MessageDescriptor,
  )";
  *fout << std::to_string(max_id + 1) + "> descriptors{{";

  for (int i = 0; i <= max_id; i++) {
    const google::protobuf::FieldDescriptor* event =
        ftrace_event->FindFieldByNumber(i);
    // Skip events that don't exist or are not messages. (Proxy for events)
    if (!event ||
        event->type() != google::protobuf::FieldDescriptor::TYPE_MESSAGE) {
      *fout << "{nullptr, 0, {}},";
      continue;
    }

    const auto* event_descriptor = event->message_type();

    // Find the max field id in the event.
    int max_field_id = 0;
    for (int j = 0; j < event_descriptor->field_count(); j++)
      max_field_id =
          std::max(max_field_id, event_descriptor->field(j)->number());

    *fout << "{\"" + event->name() + "\", " << max_field_id << ", "
          << "{";

    for (int j = 0; j <= max_field_id; j++) {
      const auto* field = event_descriptor->FindFieldByNumber(j);
      // Skip fields that don't exist or are nested messages.
      if (!field ||
          field->type() == google::protobuf::FieldDescriptor::TYPE_MESSAGE) {
        *fout << "{},";
        continue;
      }
      ProtoType type = ProtoType::FromDescriptor(field->type());
      *fout << "{\"" + field->name() + "\", ProtoSchemaType::k" +
                   ToCamelCase(type.ToString()) + "},";
    }
    *fout << "},\n},";
  }
  *fout << "}};\n";
  *fout << R"(
} // namespace

MessageDescriptor* GetMessageDescriptorForId(size_t id) {
  PERFETTO_CHECK(id < descriptors.size());
  return &descriptors[id];
}

MessageDescriptor* GetMessageDescriptorForName(base::StringView name) {
  for (MessageDescriptor& descriptor : descriptors) {
    if (descriptor.name != nullptr && descriptor.name == name)
      return &descriptor;
  }
  return nullptr;
}

size_t GetDescriptorsSize() {
  return descriptors.size();
}
  )";
  *fout << "} // namespace trace_processor\n} // namespace perfetto\n";
}

}  // namespace perfetto
