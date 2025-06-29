import json
import os
from typing import Any, Optional

from src.typings import LoggerConfig
from src.utils import SingletonLogger
from src.tasks.instance.os_interaction.task import (
    OSInteractionSkillUtility,
    OSInteractionDatasetItem,
)
from src.tasks.instance.os_interaction.container import OSInteractionContainer
from src.factories.data.standard_v0121.utility import StandardDataFactoryUtility


class OSInteractionStandardDataFactory:
    """
    The class is used to format the data generated by zjh.
    There is no direct connection between the number of skills and the difficulty of the sample.
    """

    def __init__(
        self,
        raw_data_path: str,
        processed_data_path: str,
        valid_data_path: str,
        invalid_data_path: str,
        statistical_info_data_path: str,
        log_file_path: str,
    ):
        self.raw_data_path = raw_data_path
        self.processed_data_path = processed_data_path
        self.valid_data_path = valid_data_path
        self.invalid_data_path = invalid_data_path
        self.statistical_info_data_path = statistical_info_data_path
        logger_config = LoggerConfig(
            level="INFO",
            log_file_path=log_file_path,
            logger_name="os_interaction_standard_data_factory",
        )
        self.logger = SingletonLogger.get_instance(logger_config)

    def process(self) -> None:
        raw_data_dict: dict[str, Any] = json.load(open(self.raw_data_path, "r"))
        processed_data_dict: dict[str, Any] = {}
        for key, raw_value in raw_data_dict.items():
            # region Process the data
            processed_value = {
                "instruction": raw_value["description"],
                "initialization_command_item": raw_value[
                    "initialization_command_item_list"
                ][0],
                "evaluation_info": {
                    "evaluation_command_item": raw_value["evaluation_info_dict"][
                        "evaluation_command_item"
                    ],
                    "ground_truth_command_item": raw_value["evaluation_info_dict"][
                        "ground_truth_extraction_command_item"
                    ],
                },
                "skill_list": raw_value["skill"],
                "difficulty_level": raw_value["difficulty"],
            }
            # endregion
            # region Do some validation
            for skill in processed_value["skill_list"]:
                assert OSInteractionSkillUtility.is_valid_skill(skill)
            # endregion
            processed_data_dict[key] = processed_value
        json.dump(
            processed_data_dict, open(self.processed_data_path, "w"), indent=2  # noqa
        )

    @staticmethod
    def _init_container(
        dataset_item: OSInteractionDatasetItem,
    ) -> Optional[OSInteractionContainer]:
        container = OSInteractionContainer(command_execution_timeout=5)
        execution_result = container.execute_independent(
            dataset_item.initialization_command_item
        )
        if execution_result.timeout_flag or execution_result.exit_code != 0:
            container.terminate()
            return None
        return container

    def validate(self) -> None:
        processed_data_dict: dict[str, Any] = json.load(
            open(self.processed_data_path, "r")
        )
        valid_data_dict = {}
        invalid_data_dict = {}
        for sample_index, entry in processed_data_dict.items():
            dataset_item = OSInteractionDatasetItem.model_validate(entry)
            container = OSInteractionStandardDataFactory._init_container(dataset_item)
            if container is None:
                self.logger.error(
                    f"Sample index: {sample_index:<3}. Evaluation result: Initialization failed."
                )
                invalid_data_dict[sample_index] = "Initialization failed."
                continue
            evaluation_result = container.execute_independent(
                dataset_item.evaluation_info.evaluation_command_item,
            )
            container.terminate()
            if evaluation_result.exit_code == 0:
                self.logger.error(
                    f"Sample index: {sample_index:<3}. Evaluation result: Trivial."
                )
                invalid_data_dict[sample_index] = "Trivial"
            else:
                container = OSInteractionStandardDataFactory._init_container(
                    dataset_item
                )
                assert isinstance(container, OSInteractionContainer)
                _ = container.execute_independent(
                    dataset_item.evaluation_info.ground_truth_command_item
                )
                evaluation_result = container.execute_independent(
                    dataset_item.evaluation_info.evaluation_command_item,
                )
                container.terminate()
                if evaluation_result.exit_code == 0:
                    log_func = self.logger.info
                    valid_data_dict[sample_index] = entry
                else:
                    log_func = self.logger.error
                    invalid_data_dict[sample_index] = "Exit code not 0."
                log_func(
                    f"Sample index: {sample_index:<3}. Evaluation result: [Exit code]{evaluation_result.exit_code}"
                )
        self.logger.info(f"Valid data count: {len(valid_data_dict)}")
        # Need to reset the index of the valid data.
        json.dump(valid_data_dict, open(self.valid_data_path, "w"), indent=2)  # noqa
        json.dump(
            invalid_data_dict, open(self.invalid_data_path, "w"), indent=2  # noqa
        )

    def count(self) -> None:
        valid_data_dict: dict[str, Any] = json.load(open(self.valid_data_path, "r"))
        skill_to_count_dict = {
            key: 0 for key in OSInteractionSkillUtility.get_all_skill_list()
        }
        difficulty_level_to_count_dict: dict[int, int] = {key: 0 for key in range(5)}
        for entry in valid_data_dict.values():
            dataset_item = OSInteractionDatasetItem.model_validate(entry)
            for skill in dataset_item.get_skill_list():
                skill_to_count_dict[skill] += 1
            difficulty_level = dataset_item.get_difficulty_level()
            if difficulty_level not in difficulty_level_to_count_dict:
                difficulty_level_to_count_dict[difficulty_level] = 0
            difficulty_level_to_count_dict[difficulty_level] += 1
        self.logger.info("Skill count:")
        self.logger.info(f"| {'Level':<10} | Count")
        for skill, count in skill_to_count_dict.items():
            self.logger.info(f"| {skill:<10} | {count:<5}")
        self.logger.info("Difficulty level count:")
        self.logger.info("| Level | Count")
        for level, count in difficulty_level_to_count_dict.items():
            self.logger.info(f"| {level:<5} | {count:<5}")
        statistical_info_dict = {
            "skill_to_count_dict": skill_to_count_dict,
            "difficulty_level_to_count_dict": difficulty_level_to_count_dict,
        }
        json.dump(
            statistical_info_dict,
            open(self.statistical_info_data_path, "w"),  # noqa
            indent=2,
        )


def main() -> None:
    # # region Preprocess the data
    # # The raw data is already post-processed by zjh.
    # root_dir = "data/v0121/os_interaction/v0123_1841/"
    # raw_data_path = os.path.join(root_dir, "postprocess_generated_data.json")
    # processed_data_path = os.path.join(root_dir, "os_interaction_processed.json")
    # valid_data_path = os.path.join(root_dir, "os_interaction_valid.json")
    # invalid_data_path = os.path.join(root_dir, "os_interaction_invalid.json")
    # statistical_info_data_path = os.path.join(
    #     root_dir, "os_interaction_statistical_info.json"
    # )
    # log_file_path = "./outputs/os_interaction_standard_data_factory.log"
    # os_interaction_standard_data_factory = OSInteractionStandardDataFactory(
    #     raw_data_path,
    #     processed_data_path,
    #     valid_data_path,
    #     invalid_data_path,
    #     statistical_info_data_path,
    #     log_file_path,
    # )
    # os_interaction_standard_data_factory.process()
    # os_interaction_standard_data_factory.validate()
    # os_interaction_standard_data_factory.count()
    # # endregion

    # region Merge the results
    source_identifier_list = ["v0122", "v0123_1305", "v0123_1841"]
    source_info_list = [
        (
            source_identifier,
            os.path.join(
                "data/v0121/os_interaction",
                source_identifier,
                f"os_interaction_valid.json",
            ),
        )
        for source_identifier in source_identifier_list
    ]
    StandardDataFactoryUtility.merge_data_dict(
        source_info_list,
        "data/v0121/os_interaction/os_interaction.json",
        "data/v0121/os_interaction/merged_source_information.json",
        lambda x: x["instruction"],  # type: ignore[index]
    )
    # endregion


if __name__ == "__main__":
    main()
